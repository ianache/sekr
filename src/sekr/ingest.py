"""Driver-independent projection of a validated SEKR JSON dataset."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from sekr.db import validate_dataset_json
from sekr.errors import StructuredError


@dataclass(frozen=True)
class GraphNode:
    kind: str
    key: str
    properties: Mapping[str, object]


@dataclass(frozen=True)
class GraphRelationship:
    key: str
    source_kind: str
    source_key: str
    target_kind: str
    target_key: str
    properties: Mapping[str, object]


@dataclass(frozen=True)
class GraphProjection:
    dataset: GraphNode
    nodes: tuple[GraphNode, ...]
    relationships: tuple[GraphRelationship, ...]


def _read_dataset(path: str | Path) -> dict[str, object]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StructuredError(
            "INVALID_DATASET", "Dataset JSON could not be read", {"error": str(error)}
        ) from error


def _node_properties(
    kind: str, record: Mapping[str, object], optional_fields: tuple[str, ...] = ()
) -> dict[str, object]:
    """Copy source data and make absent optional values explicit for adapters."""
    properties = dict(record)
    properties["kind"] = kind
    for field in optional_fields:
        properties.setdefault(field, None)
    return properties


def _structural_properties(relation_type: str) -> dict[str, object]:
    return {"relation_type": relation_type, "evidence": None, "confidence": "UNKNOWN"}


def build_graph_projection(path: str | Path) -> GraphProjection:
    """Validate a JSON dataset and return its canonical graph projection."""
    data = _read_dataset(path)
    validate_dataset_json(data)

    metadata = data["metadata"]
    artifacts = sorted(data["artifacts"], key=lambda record: record["id"])
    facts = sorted(data["facts"], key=lambda record: record["id"])
    profiles = sorted(data["task_profiles"], key=lambda record: record["id"])
    relations = sorted(data["relations"], key=lambda record: record["id"])

    dataset = GraphNode(
        "Dataset",
        metadata["version"],
        _node_properties("Dataset", metadata, ("description",)),
    )
    artifact_nodes = tuple(
        GraphNode(
            "Artifact",
            artifact["id"],
            _node_properties("Artifact", artifact, ("description", "path")),
        )
        for artifact in artifacts
    )
    fact_nodes = tuple(
        GraphNode(
            "Fact",
            fact["id"],
            _node_properties(
                "Fact",
                fact,
                ("artifact_id", "source", "freshness", "source_version", "valid_from", "scope", "owner"),
            ),
        )
        for fact in facts
    )
    profile_nodes = tuple(
        GraphNode(
            "TaskProfile",
            profile["id"],
            _node_properties(
                "TaskProfile",
                {**profile, "expected_artifacts": sorted(profile["expected_artifacts"])},
                ("terms", "expected_artifact_types", "expected_artifacts"),
            ),
        )
        for profile in profiles
    )

    dataset_artifact_relationships = tuple(
        GraphRelationship(
            f"dataset:{dataset.key}:artifact:{artifact['id']}",
            "Dataset",
            dataset.key,
            "Artifact",
            artifact["id"],
            _structural_properties("HAS_ARTIFACT"),
        )
        for artifact in artifacts
    )
    artifact_fact_relationships = tuple(
        GraphRelationship(
            f"artifact:{fact['artifact_id']}:fact:{fact['id']}",
            "Artifact",
            fact["artifact_id"],
            "Fact",
            fact["id"],
            _structural_properties("HAS_FACT"),
        )
        for fact in facts
        if fact.get("artifact_id") is not None
    )
    dataset_profile_relationships = tuple(
        GraphRelationship(
            f"dataset:{dataset.key}:profile:{profile['id']}",
            "Dataset",
            dataset.key,
            "TaskProfile",
            profile["id"],
            _structural_properties("HAS_PROFILE"),
        )
        for profile in profiles
    )
    profile_artifact_relationships = tuple(
        GraphRelationship(
            f"profile:{profile['id']}:artifact:{artifact_id}",
            "TaskProfile",
            profile["id"],
            "Artifact",
            artifact_id,
            _structural_properties("EXPECTS_ARTIFACT"),
        )
        for profile in profiles
        for artifact_id in sorted(profile["expected_artifacts"])
    )
    source_relationships = tuple(
        GraphRelationship(
            relation["id"],
            "Artifact",
            relation["source_id"],
            "Artifact",
            relation["target_id"],
            {
                **relation,
                "evidence": relation.get("evidence", []),
                "confidence": relation.get("confidence", "UNKNOWN"),
            },
        )
        for relation in relations
    )

    return GraphProjection(
        dataset=dataset,
        nodes=artifact_nodes + fact_nodes + profile_nodes,
        relationships=(
            dataset_artifact_relationships
            + artifact_fact_relationships
            + dataset_profile_relationships
            + profile_artifact_relationships
            + source_relationships
        ),
    )
