"""Stdio MCP adapter for the local deterministic context compiler."""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from sekr.compiler import ContextCompiler
from sekr.db import KnowledgeRepository
from sekr.errors import StructuredError


def _json_result(payload: dict[str, object], *, is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, sort_keys=True))],
        isError=is_error,
    )


def create_server(db_path: str | Path) -> FastMCP:
    compiler = ContextCompiler(KnowledgeRepository(db_path))
    server = FastMCP("SEKR Context Compiler")

    @server.tool(name="compile_context", description="Compile deterministic context for a task.")
    def compile_context(task: object, budget: object) -> CallToolResult:
        try:
            return _json_result(compiler.compile(task, budget).to_dict())
        except StructuredError as error:
            return _json_result({"error": error.to_dict()}, is_error=True)

    return server


def run_server(db_path: str | Path) -> None:
    create_server(db_path).run(transport="stdio")
