"""Neo4j persistence boundary for driver-independent graph projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sekr.errors import StructuredError

if TYPE_CHECKING:
    from sekr.ingest import GraphProjection


_LABELS = {
    "Dataset": "Dataset",
    "Artifact": "Artifact",
    "Fact": "Fact",
    "TaskProfile": "TaskProfile",
}


@dataclass(frozen=True)
class IngestSummary:
    nodes_written: int
    relationships_written: int


def _error(code: str, message: str, error: Exception) -> StructuredError:
    """Create a stable error without copying connection credentials."""
    return StructuredError(code, message, {"error_type": type(error).__name__})


def _close_quietly(resource: object | None) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:
        pass


def write_projection(
    projection: GraphProjection,
    *,
    uri: str,
    user: str,
    password: str,
) -> IngestSummary:
    """Persist one projection atomically and return deterministic counts."""
    try:
        from neo4j import GraphDatabase
    except ImportError as error:
        raise _error(
            "NEO4J_CONNECTION_ERROR", "Neo4j driver is not installed", error
        ) from error

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
    except Exception as error:
        raise _error(
            "NEO4J_CONNECTION_ERROR", "Could not create Neo4j driver", error) from error

    session = None
    transaction = None
    try:
        try:
            session = driver.session()
            transaction = session.begin_transaction()
        except Exception as error:
            raise _error(
                "NEO4J_CONNECTION_ERROR", "Could not connect to Neo4j", error
            ) from error

        try:
            for node in (projection.dataset, *projection.nodes):
                label = _LABELS[node.kind]
                transaction.run(
                    f"MERGE (n:{label} {{id: $id}}) SET n += $properties",
                    id=node.key,
                    properties=dict(node.properties),
                )

            for relationship in projection.relationships:
                source_label = _LABELS[relationship.source_kind]
                target_label = _LABELS[relationship.target_kind]
                transaction.run(
                    "MATCH (source:%s {id: $source_id}) "
                    "MATCH (target:%s {id: $target_id}) "
                    "MERGE (source)-[relationship:RELATES_TO {id: $id}]->(target) "
                    "SET relationship += $properties" % (source_label, target_label),
                    source_id=relationship.source_key,
                    target_id=relationship.target_key,
                    id=relationship.key,
                    properties=dict(relationship.properties),
                )

            transaction.commit()
        except Exception as error:
            try:
                transaction.rollback()
            except Exception:
                pass
            raise _error(
                "NEO4J_WRITE_ERROR", "Could not write Neo4j projection", error
            ) from error
    finally:
        _close_quietly(session)
        _close_quietly(driver)

    return IngestSummary(
        nodes_written=1 + len(projection.nodes),
        relationships_written=len(projection.relationships),
    )
