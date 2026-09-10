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
    from mcp.server.fastmcp.utilities.func_metadata import ArgModelBase
    from pydantic import ConfigDict

    class _RuntimeArguments(ArgModelBase):
        """Preserve raw inputs so the tool can enforce its public contract."""

        model_config = ConfigDict(extra="allow")
        task: object = None
        budget: object = None
        db: object = None

        def model_dump_one_level(self) -> dict[str, object]:
            return {**super().model_dump_one_level(), **(self.__pydantic_extra__ or {})}

    server = FastMCP("sekr")
    configured_db_path = str(db_path)

    @server.tool(
        name="compile_context",
        description="Compile evidence-backed context for a bounded task",
    )
    def compile_context(
        task: object = None,
        budget: object = None,
        db: object = None,
        **unexpected: object,
    ):
        try:
            if unexpected:
                raise StructuredError(
                    "INVALID_INPUT",
                    "Unexpected tool arguments",
                    {"fields": sorted(unexpected)},
                )
            if not isinstance(task, str) or not task.strip():
                raise StructuredError("INVALID_TASK", "Task must be non-empty text")
            if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
                raise StructuredError(
                    "INVALID_BUDGET", "Budget must be a non-negative integer"
                )
            if not isinstance(db, str) or not db.strip():
                raise StructuredError("INVALID_DATABASE", "Database path must be non-empty")
            package = ContextCompiler(
                KnowledgeRepository(configured_db_path)
            ).compile(task, budget)
            return _tool_result(package.to_dict(), is_error=False)
        except StructuredError as error:
            return _tool_result({"error": error.to_dict()}, is_error=True)
        except Exception:
            error = StructuredError("DATABASE_ERROR", "Database could not be read")
            return _tool_result({"error": error.to_dict()}, is_error=True)

    # FastMCP derives its schema from the function signature.  Replace it with
    # the public contract and preserve raw call values for strict validation.
    tool = server._tool_manager._tools["compile_context"]
    tool.parameters = dict(_INPUT_SCHEMA)
    tool.fn_metadata.arg_model = _RuntimeArguments
    return server


def run_server(db_path: str | Path) -> None:
    """Run the MCP server over stdio, reserving stdout for JSON-RPC messages."""
    create_server(db_path).run(transport="stdio")
