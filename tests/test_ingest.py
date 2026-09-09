import json
from collections import Counter
from pathlib import Path

import pytest

from sekr.errors import StructuredError
from sekr.ingest import build_graph_projection


DATASET = Path("data/coder_activation.json")


def test_projection_has_expected_fixture_counts_and_version():
    """Catches omitted source records or graph edges during projection."""
    projection = build_graph_projection(DATASET)

    assert projection.dataset.properties["version"] == "0.1.0"
    assert {node.kind for node in projection.nodes} == {"Artifact", "Fact", "TaskProfile"}
    assert Counter(node.kind for node in projection.nodes) == {
        "Artifact": 9,
        "Fact": 2,
        "TaskProfile": 1,
    }
    assert len(projection.nodes) == 12
    assert Counter(
        relationship.properties["relation_type"]
        for relationship in projection.relationships
    ) == {
        "HAS_ARTIFACT": 9,
        "HAS_FACT": 2,
        "HAS_PROFILE": 1,
        "EXPECTS_ARTIFACT": 7,
        "exposed_by": 1,
        "calls": 1,
        "uses": 1,
        "persists_to": 1,
        "verified_by": 1,
        "constrained_by": 1,
    }
    assert len(projection.relationships) == 25


def test_projection_is_deterministic():
    """Catches projection output that depends on JSON input order."""
    assert build_graph_projection(DATASET) == build_graph_projection(DATASET)


def test_projection_is_deterministic_when_profile_artifacts_are_reordered(tmp_path):
    """Catches profile source ordering leaking into graph nodes or relationships."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["task_profiles"][0]["expected_artifacts"].reverse()
    reordered_source = tmp_path / "reordered.json"
    reordered_source.write_text(json.dumps(data), encoding="utf-8")

    assert build_graph_projection(DATASET) == build_graph_projection(reordered_source)


def test_projection_preserves_graph_contract_properties():
    """Catches dropping provenance or relationship semantics during projection."""
    projection = build_graph_projection(DATASET)
    artifact = next(node for node in projection.nodes if node.key == "endpoint.coder_values")
    source_relation = next(
        relationship
        for relationship in projection.relationships
        if relationship.key == "relation.endpoint_service"
    )
    structural_relation = next(
        relationship
        for relationship in projection.relationships
        if relationship.source_kind == "Dataset" and relationship.target_kind == "Artifact"
    )

    assert artifact.properties["kind"] == "Artifact"
    assert artifact.properties["evidence"] == ["tenant/api/coder_values.py:12-62"]
    assert source_relation.properties["relation_type"] == "calls"
    assert source_relation.properties["confidence"] == "VERIFIED"
    assert structural_relation.properties["relation_type"] == "HAS_ARTIFACT"
    assert structural_relation.properties["evidence"] is None
    assert structural_relation.properties["confidence"] == "UNKNOWN"


def test_projection_preserves_metadata_profile_fact_and_optional_properties(tmp_path):
    """Catches dropped source metadata or incorrect absent-value normalization."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["artifacts"][0].pop("path")
    data["facts"][0].pop("freshness")
    data["facts"][0].pop("valid_from", None)
    data["facts"][0].pop("owner")
    source = tmp_path / "optional-values.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    projection = build_graph_projection(source)
    fact = next(node for node in projection.nodes if node.key == "fact.deactivation_preserves_history")
    profile = next(node for node in projection.nodes if node.key == "profile.coder_activation")
    artifact = next(node for node in projection.nodes if node.key == "feature.tenant_coder_activation")

    assert projection.dataset.properties == {
        **data["metadata"],
        "kind": "Dataset",
    }
    assert fact.properties["source"] == "ADR 004"
    assert fact.properties["source_version"] == "0.1"
    assert fact.properties["scope"] == "Tenant Coder activation"
    assert fact.properties["freshness"] is None
    assert fact.properties["valid_from"] is None
    assert fact.properties["owner"] is None
    assert profile.properties["expected_artifacts"] == sorted(
        data["task_profiles"][0]["expected_artifacts"]
    )
    assert artifact.properties["path"] is None


def test_invalid_relation_target_fails_before_projection(tmp_path):
    """Catches a graph projection being created from a dangling relation."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["relations"][0]["target_id"] = "artifact.missing"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_REFERENCE"
