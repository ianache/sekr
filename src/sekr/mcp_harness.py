"""Dependency-light subprocess client for SEKR's MCP stdio server."""

from __future__ import annotations

import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread
from time import monotonic
from typing import Any


class MCPProtocolError(RuntimeError):
    """Raised when the MCP subprocess violates the expected JSON-RPC protocol."""


_EOF = object()


class MCPHarness:
    """Run and communicate with ``sekr mcp serve`` over newline-delimited JSON-RPC."""

    def __init__(self, db_path: str | Path, *, timeout: float = 5.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.db_path = str(db_path)
        self.timeout = timeout
        self._next_id = 1
        self._initialized = False
        self._stdout: Queue[object] = Queue()
        self._stderr: Queue[object] = Queue()
        self._stderr_lines: list[str] = []
        environment = dict(os.environ)
        source_root = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            source_root
            if not existing_pythonpath
            else os.pathsep.join((source_root, existing_pythonpath))
        )
        self._process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sekr.cli",
                "mcp",
                "serve",
                "--db",
                self.db_path,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=environment,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._start_reader(self._process.stdout, self._stdout)
        self._start_reader(self._process.stderr, self._stderr)

    def __enter__(self) -> "MCPHarness":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def stderr(self) -> str:
        """Return diagnostics emitted by the subprocess so far."""
        while True:
            try:
                item = self._stderr.get_nowait()
            except Empty:
                break
            if item is not _EOF:
                self._stderr_lines.append(str(item))
        return "".join(self._stderr_lines)

    @staticmethod
    def _start_reader(stream: Any, output: Queue[object]) -> None:
        def read_lines() -> None:
            try:
                for line in stream:
                    output.put(line)
            finally:
                output.put(_EOF)

        Thread(target=read_lines, daemon=True).start()

    def initialize(self) -> dict[str, Any]:
        """Negotiate MCP initialization and announce the initialized state."""
        response = self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "sekr-mcp-harness", "version": "0.1.0"},
            },
        )
        self._notify("notifications/initialized")
        self._initialized = True
        return response

    def list_tools(self) -> list[dict[str, Any]]:
        """Return the server's registered tools after initialization."""
        self._require_initialized()
        result = self._request("tools/list")
        tools = result.get("tools")
        if not isinstance(tools, list) or not all(isinstance(tool, dict) for tool in tools):
            raise MCPProtocolError("MCP_PROTOCOL_ERROR: tools/list returned invalid tools")
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call an MCP tool and return its result payload."""
        self._require_initialized()
        if not isinstance(name, str) or not name:
            raise ValueError("name must be non-empty text")
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        """Close stdin and stop the child process if it does not exit promptly."""
        if self._process.poll() is not None:
            return
        if self._process.stdin is not None and not self._process.stdin.closed:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=min(self.timeout, 1.0))
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=min(self.timeout, 1.0))
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise MCPProtocolError("MCP_PROTOCOL_ERROR: initialize() must be called first")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)

    def _request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._write(message)
        response = self._read_response(request_id)
        if "error" in response:
            raise MCPProtocolError(f"MCP_PROTOCOL_ERROR: server error {response['error']!r}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise MCPProtocolError("MCP_PROTOCOL_ERROR: response result must be an object")
        return result

    def _write(self, message: dict[str, Any]) -> None:
        if self._process.stdin is None or self._process.stdin.closed:
            raise MCPProtocolError("MCP_PROTOCOL_ERROR: server stdin is closed")
        try:
            self._process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self._process.stdin.flush()
        except OSError as error:
            raise MCPProtocolError("MCP_PROTOCOL_ERROR: could not write to server") from error

    def _read_response(self, request_id: int) -> dict[str, Any]:
        deadline = monotonic() + self.timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise MCPProtocolError(
                    f"MCP_PROTOCOL_ERROR: timed out waiting for response id {request_id}"
                )
            try:
                line = self._stdout.get(timeout=remaining)
            except Empty as error:
                raise MCPProtocolError(
                    f"MCP_PROTOCOL_ERROR: timed out waiting for response id {request_id}"
                ) from error
            if line is _EOF:
                raise MCPProtocolError(
                    f"MCP_PROTOCOL_ERROR: server reached EOF waiting for response id {request_id}"
                )
            try:
                response = json.loads(str(line))
            except json.JSONDecodeError as error:
                raise MCPProtocolError("MCP_PROTOCOL_ERROR: server emitted non-JSON stdout") from error
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise MCPProtocolError("MCP_PROTOCOL_ERROR: server emitted invalid JSON-RPC")
            if response.get("id") != request_id:
                raise MCPProtocolError(
                    f"MCP_PROTOCOL_ERROR: expected response id {request_id}, got {response.get('id')!r}"
                )
            return response
