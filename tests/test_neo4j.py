import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from sekr.errors import StructuredError
from sekr.ingest import build_graph_projection


DATASET = Path("data/coder_activation.json")
PASSWORD = "do-not-leak-this-password"


class RecordingTransaction:
    def __init__(self, fail_on=None):
        self.runs = []
        self.committed = False
        self.rolled_back = False
        self.fail_on = fail_on

    def run(self, query, **parameters):
        self.runs.append((query, parameters))
        if self.fail_on == "run":
            raise RuntimeError(f"query failed with {PASSWORD}")

    def commit(self):
        if self.fail_on == "commit":
            raise RuntimeError(f"commit failed with {PASSWORD}")
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class RecordingSession:
    def __init__(self, fail_on=None):
        self.transaction = RecordingTransaction(fail_on)
        self.closed = False
        self.fail_on = fail_on

    def begin_transaction(self):
        if self.fail_on == "begin_transaction":
            raise RuntimeError(f"authentication failed with {PASSWORD}")
        return self.transaction

    def close(self):
        self.closed = True


class RecordingDriver:
    def __init__(self, fail_on=None):
        self.session_instance = RecordingSession(fail_on)
        self.closed = False
        self.fail_on = fail_on

    def session(self):
        if self.fail_on == "session":
            raise RuntimeError(f"connection failed with {PASSWORD}")
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


@pytest.mark.parametrize("failure_point", ["session", "begin_transaction"])
def test_write_projection_maps_session_connection_failures_without_password(
    monkeypatch, failure_point
):
    """Catches lazy connection failures being misclassified as write errors."""
    from sekr.neo4j import write_projection

    driver = RecordingDriver(fail_on=failure_point)
    monkeypatch.setitem(
        sys.modules,
        "neo4j",
        SimpleNamespace(GraphDatabase=SimpleNamespace(driver=lambda uri, auth: driver)),
    )

    with pytest.raises(StructuredError) as error:
        write_projection(
            build_graph_projection(DATASET),
            uri="bolt://example.test:7687",
            user="neo4j",
            password=PASSWORD,
        )

    assert error.value.code == "NEO4J_CONNECTION_ERROR"
    assert PASSWORD not in str(error.value.details)
    assert driver.closed
    assert driver.session_instance.closed is (failure_point == "begin_transaction")
    assert not driver.session_instance.transaction.rolled_back


@pytest.mark.parametrize("failure_point", ["run", "commit"])
def test_write_projection_maps_write_failures_rolls_back_and_hides_password(
    monkeypatch, failure_point
):
    """Catches query or commit failures escaping the write error contract."""
    from sekr.neo4j import write_projection

    driver = RecordingDriver(fail_on=failure_point)
    monkeypatch.setitem(
        sys.modules,
        "neo4j",
        SimpleNamespace(GraphDatabase=SimpleNamespace(driver=lambda uri, auth: driver)),
    )

    with pytest.raises(StructuredError) as error:
        write_projection(
            build_graph_projection(DATASET),
            uri="bolt://example.test:7687",
            user="neo4j",
            password=PASSWORD,
        )

    assert error.value.code == "NEO4J_WRITE_ERROR"
    assert PASSWORD not in str(error.value.details)
    assert driver.session_instance.transaction.rolled_back
    assert not driver.session_instance.transaction.committed
    assert driver.session_instance.closed
    assert driver.closed


@pytest.mark.skipif(
    not all(
        os.getenv(name)
        for name in ("SEKR_NEO4J_URI", "SEKR_NEO4J_USER", "SEKR_NEO4J_PASSWORD")
    ),
    reason="SEKR_NEO4J_URI, SEKR_NEO4J_USER, and SEKR_NEO4J_PASSWORD are required",
)
def test_live_neo4j_ingestion_is_repeatable():
    from sekr.neo4j import write_projection

    projection = build_graph_projection(DATASET)
    first = write_projection(
        projection,
        uri=os.environ["SEKR_NEO4J_URI"],
        user=os.environ["SEKR_NEO4J_USER"],
        password=os.environ["SEKR_NEO4J_PASSWORD"],
    )
    second = write_projection(
        projection,
        uri=os.environ["SEKR_NEO4J_URI"],
        user=os.environ["SEKR_NEO4J_USER"],
        password=os.environ["SEKR_NEO4J_PASSWORD"],
    )

    assert first == second

    from neo4j import GraphDatabase

    with GraphDatabase.driver(
        os.environ["SEKR_NEO4J_URI"],
        auth=(os.environ["SEKR_NEO4J_USER"], os.environ["SEKR_NEO4J_PASSWORD"]),
    ) as driver, driver.session() as session:
        node_count = session.run(
            "MATCH (node) WHERE "
            "(node:Dataset AND node.id = $dataset_id) OR "
            "(node:Artifact AND node.id IN $artifact_ids) OR "
            "(node:Fact AND node.id IN $fact_ids) OR "
            "(node:TaskProfile AND node.id IN $profile_ids) "
            "RETURN count(node) AS count",
            dataset_id=projection.dataset.key,
            artifact_ids=[node.key for node in projection.nodes if node.kind == "Artifact"],
            fact_ids=[node.key for node in projection.nodes if node.kind == "Fact"],
            profile_ids=[node.key for node in projection.nodes if node.kind == "TaskProfile"],
        ).single()["count"]
        relationship_count = session.run(
            "MATCH ()-[relationship:RELATES_TO]->() "
            "WHERE relationship.id IN $relationship_ids "
            "RETURN count(relationship) AS count",
            relationship_ids=[relationship.key for relationship in projection.relationships],
        ).single()["count"]

    assert node_count == first.nodes_written
    assert relationship_count == first.relationships_written
