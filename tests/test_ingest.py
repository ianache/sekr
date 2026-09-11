import json
from collections import Counter
from pathlib import Path

import pytest

from sekr.errors import StructuredError
from sekr.ingest import build_graph_projection
from sekr.knowledge_check import check_knowledge, projection_to_snapshot


DATASET = Path("data/coder_activation.json")


def test_projection_has_expected_fixture_counts_and_version():
    """Catches omitted source records or graph edges during projection."""
    projection = build_graph_projection(DATASET)

    assert projection.dataset.kind == "Dataset"
    assert projection.dataset.key == "0.1.0"
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


def test_projection_carries_provenance_on_artifact_fact_and_relation(tmp_path):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    provenance = {
        "source": "ADR 004",
        "evidence": ["docs/adr.md:1-2"],
        "source_version": "0.1",
        "content_hash": "sha256:" + "a" * 64,
        "observed_at": "2026-09-11T00:00:00Z",
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-09-30T00:00:00Z",
    }
    data["artifacts"][0].update(provenance)
    data["facts"][0].update(provenance)
    data["relations"][0].update(provenance)
    source = tmp_path / "provenance.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    projection = build_graph_projection(source)
    artifact = next(node for node in projection.nodes if node.key == data["artifacts"][0]["id"])
    fact = next(node for node in projection.nodes if node.key == data["facts"][0]["id"])
    relation = next(edge for edge in projection.relationships if edge.key == data["relations"][0]["id"])

    for record in (artifact, fact, relation):
        assert {field: record.properties[field] for field in provenance} == provenance


@pytest.mark.parametrize("field", ("source", "source_version", "content_hash", "observed_at", "valid_from", "valid_until"))
def test_projection_rejects_explicit_null_scalar_provenance(tmp_path, field):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["artifacts"][0][field] = None
    source = tmp_path / f"invalid-{field}.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_PROVENANCE"
    assert error.value.details["field"] == field


@pytest.mark.parametrize("collection", ("artifacts", "relations", "facts", "task_profiles"))
def test_projection_rejects_duplicate_record_ids_before_projection(tmp_path, collection):
    """Catches JSON duplicate IDs that SQLite primary keys would reject."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data[collection].append(dict(data[collection][0]))
    source = tmp_path / f"duplicate-{collection}.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_DATASET"


@pytest.mark.parametrize(
    "collection",
    ("metadata", "artifacts", "relations", "facts", "task_profiles"),
)
def test_projection_rejects_unknown_model_fields_before_projection(tmp_path, collection):
    """Catches fields P1 dataclass construction would reject during a load."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    record = data[collection] if collection == "metadata" else data[collection][0]
    record["unexpected"] = "value"
    source = tmp_path / f"unknown-{collection}.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_DATASET"


def test_projection_normalizes_omitted_profile_expected_artifacts_to_empty(tmp_path):
    """Catches valid profiles without optional expected-artifact references crashing P2."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["task_profiles"][0].pop("expected_artifacts")
    source = tmp_path / "profile-without-expected-artifacts.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    projection = build_graph_projection(source)
    profile = next(node for node in projection.nodes if node.kind == "TaskProfile")

    assert profile.properties["expected_artifacts"] == []
    assert not any(
        relationship.properties["relation_type"] == "EXPECTS_ARTIFACT"
        for relationship in projection.relationships
    )


def test_projection_materializes_artifact_and_fact_provenance_defaults(tmp_path):
    """Catches omitted provenance retaining stale values on a later Neo4j MERGE."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["artifacts"][0].pop("evidence")
    data["artifacts"][0].pop("confidence")
    data["facts"][0].pop("evidence")
    data["facts"][0].pop("confidence")
    source = tmp_path / "default-provenance.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    projection = build_graph_projection(source)
    artifact = next(node for node in projection.nodes if node.key == data["artifacts"][0]["id"])
    fact = next(node for node in projection.nodes if node.key == data["facts"][0]["id"])

    assert artifact.properties["evidence"] == []
    assert artifact.properties["confidence"] == "UNKNOWN"
    assert fact.properties["evidence"] == []
    assert fact.properties["confidence"] == "UNKNOWN"


def test_knowledge_check_accepts_projection_without_optional_provenance(tmp_path):
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    optional_fields = (
        "source", "evidence", "source_version", "content_hash",
        "observed_at", "valid_from", "valid_until",
    )
    source = tmp_path / "legacy-without-provenance.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    snapshot = projection_to_snapshot(build_graph_projection(source))
    for record in (*snapshot["nodes"], *snapshot["relationships"]):
        properties = record["properties"]
        for field in optional_fields:
            properties.pop(field, None)

    assert check_knowledge(snapshot, snapshot).valid is True


def test_invalid_relation_target_fails_before_projection(tmp_path):
    """Catches a graph projection being created from a dangling relation."""
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    data["relations"][0]["target_id"] = "artifact.missing"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)

    assert error.value.code == "INVALID_REFERENCE"
