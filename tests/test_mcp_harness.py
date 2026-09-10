"""Subprocess protocol tests for the dependency-light MCP client."""

from importlib.util import find_spec
from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    find_spec("mcp") is None, reason="MCP SDK is not installed"
)

from sekr.db import init_db, load_dataset
from sekr.compiler import ContextCompiler
from sekr.db import KnowledgeRepository
from sekr.mcp_harness import MCPHarness


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def test_harness_forces_utf8_for_all_subprocess_pipes(seeded_db, monkeypatch):
    """Catches Windows locale defaults corrupting UTF-8 JSON-RPC text."""
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")

    with MCPHarness(seeded_db, timeout=5) as harness:
        process = harness._process
        encodings = (
            process.stdin.encoding,
            process.stdout.encoding,
            process.stderr.encoding,
        )

    assert tuple(encoding.lower().replace("-", "") for encoding in encodings) == (
        "utf8",
        "utf8",
        "utf8",
    )


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


def test_harness_matches_direct_compiler_and_excludes_oracle_fields(seeded_db):
    request = {
        "task": "activate coder values",
        "budget": 6,
        "db": str(seeded_db),
    }
    expected = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        request["task"], request["budget"]
    ).to_dict()

    with MCPHarness(seeded_db, timeout=5) as harness:
        harness.initialize()
        result = harness.call_tool("compile_context", request)

    assert result["isError"] is False
    assert result["structuredContent"] == expected
    encoded = str(result["structuredContent"]).lower()
    assert "oracle" not in encoded
    assert "expected_artifact_ids" not in encoded
    assert "critical_artifact_ids" not in encoded


@pytest.mark.parametrize(
    "request_payload, code",
    [
        ({"task": "", "budget": 3, "db": "ignored"}, "INVALID_TASK"),
        ({"task": "activate coder values", "budget": -1, "db": "ignored"}, "INVALID_BUDGET"),
    ],
)
def test_harness_returns_structured_invalid_request(request_payload, code, seeded_db):
    request_payload["db"] = str(seeded_db)
    with MCPHarness(seeded_db, timeout=5) as harness:
        harness.initialize()
        result = harness.call_tool("compile_context", request_payload)

    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == code
