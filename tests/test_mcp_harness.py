"""Subprocess protocol tests for the dependency-light MCP client."""

from pathlib import Path

import pytest

from sekr.db import init_db, load_dataset
from sekr.mcp_harness import MCPHarness


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def test_harness_initializes_discovers_and_calls_compiler_deterministically(seeded_db):
    with MCPHarness(seeded_db, timeout=5) as harness:
        info = harness.initialize()
        tools = harness.list_tools()
        arguments = {
            "task": "activate coder values",
            "budget": 6,
            "db": str(seeded_db),
        }
        first = harness.call_tool("compile_context", arguments)
        second = harness.call_tool("compile_context", arguments)

    assert info["serverInfo"]["name"] == "sekr"
    assert [tool["name"] for tool in tools] == ["compile_context"]
    assert first == second
    assert first["isError"] is False
    assert first["structuredContent"]["budget"] == 6


def test_harness_returns_unknown_tool_error_without_server_crash(seeded_db):
    with MCPHarness(seeded_db, timeout=5) as harness:
        harness.initialize()
        error = harness.call_tool("unknown", {})
        tools = harness.list_tools()

    assert error["isError"] is True
    assert [tool["name"] for tool in tools] == ["compile_context"]
