"""Contract tests for the SEKR MCP tool registration and responses."""

import asyncio
from importlib.util import find_spec
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    find_spec("mcp") is None, reason="MCP SDK is not installed"
)

from sekr.compiler import ContextCompiler
from sekr.db import KnowledgeRepository, init_db, load_dataset
from sekr.mcp_server import create_server


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def _tool(server):
    tools = server._tool_manager._tools
    assert tuple(tools) == ("compile_context",)
    return tools["compile_context"]


def _invoke(server, arguments):
    return asyncio.run(_tool(server).run(arguments))


def test_compile_context_registration_has_the_required_input_schema(seeded_db):
    schema = _tool(create_server(seeded_db)).parameters

    assert schema == {
        "type": "object",
        "properties": {
            "task": {"type": "string", "minLength": 1},
            "budget": {"type": "integer", "minimum": 0},
            "db": {"type": "string", "minLength": 1},
        },
        "required": ["task", "budget", "db"],
        "additionalProperties": False,
    }


def test_compile_context_returns_the_canonical_package_and_json_text(seeded_db):
    arguments = {"task": "activate coder values", "budget": 6, "db": str(seeded_db)}

    result = _invoke(create_server(seeded_db), arguments)
    expected = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "activate coder values", 6
    ).to_dict()

    assert result.isError is False
    assert result.structuredContent == expected
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert json.loads(result.content[0].text) == expected


@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"task": "", "budget": 1, "db": "knowledge.sqlite"}, "INVALID_TASK"),
        ({"task": "task", "budget": -1, "db": "knowledge.sqlite"}, "INVALID_BUDGET"),
        ({"task": "task", "budget": 1, "db": ""}, "INVALID_DATABASE"),
    ],
)
def test_compile_context_returns_structured_errors_for_invalid_inputs(
    seeded_db, arguments, code
):
    result = _invoke(create_server(seeded_db), arguments)

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == code
    assert result.structuredContent["error"]["details"] == {}
    assert len(result.content) == 1
    assert json.loads(result.content[0].text) == result.structuredContent


@pytest.mark.parametrize(
    "arguments, code",
    [
        ({"task": "task", "budget": 1, "db": "knowledge.sqlite", "extra": True}, "INVALID_INPUT"),
        ({"task": "task", "budget": "1", "db": "knowledge.sqlite"}, "INVALID_BUDGET"),
        ({"task": "task", "budget": True, "db": "knowledge.sqlite"}, "INVALID_BUDGET"),
        ({"task": 1, "budget": 1, "db": "knowledge.sqlite"}, "INVALID_TASK"),
        ({"task": "task", "budget": 1, "db": 1}, "INVALID_DATABASE"),
    ],
)
def test_compile_context_enforces_its_runtime_input_contract(seeded_db, arguments, code):
    result = _invoke(create_server(seeded_db), arguments)

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == code
    assert len(result.content) == 1
    assert json.loads(result.content[0].text) == result.structuredContent


def test_compile_context_cannot_be_redirected_to_a_client_database(seeded_db, tmp_path):
    client_database = tmp_path / "client-selected.sqlite"
    result = _invoke(
        create_server(seeded_db),
        {
            "task": "activate coder values",
            "budget": 1,
            "db": str(client_database),
        },
    )
    expected = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "activate coder values", 1
    ).to_dict()

    assert result.isError is False
    assert result.structuredContent == expected
    assert json.loads(result.content[0].text) == expected


def test_compile_context_returns_a_sanitized_structured_database_error(seeded_db, tmp_path):
    database_directory = tmp_path / "not-a-database"
    database_directory.mkdir()
    result = _invoke(
        create_server(database_directory),
        {"task": "activate coder values", "budget": 1, "db": str(seeded_db)},
    )

    assert result.isError is True
    assert result.structuredContent["error"]["code"] == "DATABASE_ERROR"
    assert str(database_directory) not in json.dumps(result.structuredContent)
    assert str(database_directory) not in result.content[0].text


def test_create_server_does_not_write_to_stdout(seeded_db, capsys):
    create_server(seeded_db)

    captured = capsys.readouterr()
    assert captured.out == ""
