import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import pytest

from sekr.compiler import ContextCompiler
from sekr.db import KnowledgeRepository, init_db, load_dataset


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def _call_compile_tool(db_path, requests):
    async def run():
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path("src").resolve())
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "sekr.cli", "mcp", "serve", "--db", str(db_path)],
            env=environment,
        )
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                return [
                    await session.call_tool("compile_context", request)
                    for request in requests
                ]

    return asyncio.run(run())


def _payload(result):
    assert len(result.content) == 1
    return json.loads(result.content[0].text)


def test_mcp_compile_matches_direct_compiler_and_is_deterministic(seeded_db):
    """Catches an MCP handler that changes compiler output or ordering."""
    request = {"task": "activate coder values", "budget": 6}
    expected = ContextCompiler(KnowledgeRepository(seeded_db)).compile(**request).to_dict()

    first, second = _call_compile_tool(seeded_db, [request, request])

    assert first.isError is False
    assert second.isError is False
    assert _payload(first) == expected
    assert _payload(second) == expected


@pytest.mark.parametrize(("request_payload", "code"), [
    ({"task": "", "budget": 3}, "INVALID_TASK"),
    ({"task": "activate coder values", "budget": -1}, "INVALID_BUDGET"),
])
def test_mcp_compile_returns_structured_errors_for_invalid_requests(seeded_db, request_payload, code):
    """Catches invalid MCP requests escaping as unstructured transport failures."""
    (result,) = _call_compile_tool(seeded_db, [request_payload])

    assert result.isError is True
    assert _payload(result)["error"]["code"] == code


def test_mcp_compile_never_returns_evaluation_oracle_fields(seeded_db):
    """Catches a compile response that leaks evaluation-only oracle metadata."""
    (result,) = _call_compile_tool(
        seeded_db, [{"task": "activate coder values", "budget": 6}]
    )

    encoded = json.dumps(_payload(result), sort_keys=True)

    assert result.isError is False
    assert "expected_artifact_ids" not in encoded
    assert "critical_artifact_ids" not in encoded
    assert "oracle" not in encoded.lower()
