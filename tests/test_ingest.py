import json
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
    assert len(projection.nodes) == 12
    assert len(projection.relationships) == 25


def test_projection_is_deterministic():
    """Catches projection output that depends on JSON input order."""
    assert build_graph_projection(DATASET) == build_graph_projection(DATASET)


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
    assert structural_relation.properties["evidence"] == []
    assert structural_relation.properties["confidence"] == "UNKNOWN"


def test_invalid_relation_target_fails_before_projection(tmp_path):
    """Catches a graph projection being created from a dangling relation."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["relations"][0]["target_id"] = "artifact.missing"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_REFERENCE"
