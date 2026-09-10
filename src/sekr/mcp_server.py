"""MCP stdio server exposing the deterministic SQLite context compiler."""

import json
from pathlib import Path
from typing import Any

from sekr.compiler import ContextCompiler
from sekr.db import KnowledgeRepository
from sekr.errors import StructuredError


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "minLength": 1},
        "budget": {"type": "integer", "minimum": 0},
        "db": {"type": "string", "minLength": 1},
    },
    "required": ["task", "budget", "db"],
    "additionalProperties": False,
}


def _tool_result(payload: dict[str, Any], *, is_error: bool):
    """Return both MCP structured content and a JSON text representation."""
    from mcp.types import CallToolResult, TextContent

    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, sort_keys=True))],
        structuredContent=payload,
        isError=is_error,
    )


def create_server(db_path: str | Path):
    """Create the SEKR FastMCP server without writing diagnostics to stdout."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("sekr")

    @server.tool(
        name="compile_context",
        description="Compile evidence-backed context for a bounded task",
    )
    def compile_context(task: str, budget: int, db: str):
        try:
            if not db.strip():
                raise StructuredError("INVALID_DATABASE", "Database path must be non-empty")
            package = ContextCompiler(KnowledgeRepository(db)).compile(task, budget)
            return _tool_result(package.to_dict(), is_error=False)
        except StructuredError as error:
            return _tool_result({"error": error.to_dict()}, is_error=True)
        except Exception:
            error = StructuredError("DATABASE_ERROR", "Database could not be read")
            return _tool_result({"error": error.to_dict()}, is_error=True)

    # FastMCP derives its schema from the function signature.  Replace it with
    # the public contract so clients also reject unknown fields.
    server._tool_manager._tools["compile_context"].parameters = dict(_INPUT_SCHEMA)
    return server


def run_server(db_path: str | Path) -> None:
    """Run the MCP server over stdio, reserving stdout for JSON-RPC messages."""
    create_server(db_path).run(transport="stdio")
