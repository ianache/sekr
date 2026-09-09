import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sekr.errors import StructuredError
from sekr.ingest import build_graph_projection


DATASET = Path("data/coder_activation.json")
PASSWORD = "do-not-leak-this-password"


class RecordingTransaction:
    def __init__(self):
        self.runs = []
        self.committed = False
        self.rolled_back = False

    def run(self, query, **parameters):
        self.runs.append((query, parameters))

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class RecordingSession:
    def __init__(self):
        self.transaction = RecordingTransaction()
        self.closed = False

    def begin_transaction(self):
        return self.transaction

    def close(self):
        self.closed = True


class RecordingDriver:
    def __init__(self):
        self.session_instance = RecordingSession()
        self.closed = False

    def session(self):
        return self.session_instance

    def close(self):
        self.closed = True


def test_write_projection_uses_fixed_parameterized_merges_and_closes_driver(monkeypatch):
    """Catches a non-atomic or unsafe persistence boundary."""
    from sekr.neo4j import write_projection

    driver = RecordingDriver()
    graph_database = SimpleNamespace(driver=lambda uri, auth: driver)
    monkeypatch.setitem(sys.modules, "neo4j", SimpleNamespace(GraphDatabase=graph_database))

    summary = write_projection(
        build_graph_projection(DATASET),
        uri="bolt://example.test:7687",
        user="neo4j",
        password=PASSWORD,
    )

    transaction = driver.session_instance.transaction
    assert summary.nodes_written == 13
    assert summary.relationships_written == 25
    assert len(transaction.runs) == 38
    assert transaction.committed
    assert not transaction.rolled_back
    assert driver.session_instance.closed
    assert driver.closed
    assert all("$properties" in query for query, _ in transaction.runs)
    assert all(PASSWORD not in query for query, _ in transaction.runs)

    node_runs = transaction.runs[:13]
    relationship_runs = transaction.runs[13:]
    assert {parameters["id"] for _, parameters in node_runs} == {
        "0.1.0",
        *{node.key for node in build_graph_projection(DATASET).nodes},
    }
    assert all("MERGE (n:" in query and "{id: $id}" in query for query, _ in node_runs)
    assert {query.split("MERGE (n:")[1].split(" ")[0] for query, _ in node_runs} == {
        "Dataset",
        "Artifact",
        "Fact",
        "TaskProfile",
    }
    assert all("RELATES_TO {id: $id}" in query for query, _ in relationship_runs)
    assert all("MATCH (source:" in query and "MATCH (target:" in query for query, _ in relationship_runs)
    assert all(parameters["properties"]["relation_type"] for _, parameters in relationship_runs)


def test_write_projection_maps_connection_failures_without_leaking_password(monkeypatch):
    """Catches driver construction errors escaping the stable error contract."""
    from sekr.neo4j import write_projection

    def raise_connection_error(uri, auth):
        raise RuntimeError(f"unable to connect using {auth[1]}")

    graph_database = SimpleNamespace(driver=raise_connection_error)
    monkeypatch.setitem(sys.modules, "neo4j", SimpleNamespace(GraphDatabase=graph_database))

    with pytest.raises(StructuredError) as error:
        write_projection(
            build_graph_projection(DATASET),
            uri="bolt://example.test:7687",
            user="neo4j",
            password=PASSWORD,
        )

    assert error.value.code == "NEO4J_CONNECTION_ERROR"
    assert PASSWORD not in str(error.value.details)
