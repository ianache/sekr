import pytest

from sekr.errors import StructuredError
from pathlib import Path

from sekr.ingest import build_graph_projection
from sekr.knowledge_check import (
    build_knowledge_snapshot,
    check_knowledge,
    evaluate_knowledge_policy,
    projection_to_snapshot,
)


def _snapshot(nodes=(), relationships=()):
    return {"nodes": list(nodes), "relationships": list(relationships)}


def _node(kind, key, **properties):
    return {"kind": kind, "key": key, "properties": properties}


def _relationship(key, source_key, target_key, **extra):
    return {
        "key": key,
        "source_kind": "Artifact",
        "source_key": source_key,
        "target_kind": "Artifact",
        "target_key": target_key,
        "properties": extra,
    }


def test_knowledge_check_accepts_identical_valid_snapshot():
    snapshot = _snapshot(
        [_node("Artifact", "a", title="A"), _node("Artifact", "b", title="B")],
        [_relationship("r", "a", "b", relation_type="USES")],
    )

    report = check_knowledge(snapshot, snapshot)

    assert report.to_dict() == {
        "valid": True,
        "issues": [],
        "diff": {"nodes": {"added": [], "removed": [], "changed": []},
                 "relationships": {"added": [], "removed": [], "changed": []}},
    }


def test_knowledge_check_accepts_valid_provenance_fields():
    snapshot = _snapshot([
        _node(
            "Fact",
            "fact-a",
            source="ADR 004",
            evidence=["docs/adr.md:1-2"],
            source_version="0.1",
            content_hash="sha256:" + "a" * 64,
            observed_at="2026-09-11T00:00:00Z",
            valid_from="2026-09-01T00:00:00+00:00",
            valid_until="2026-09-30T00:00:00Z",
        )
    ])

    assert check_knowledge(snapshot, snapshot).valid is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", 42),
        ("evidence", ["docs/ok.md", 42]),
        ("source_version", 42),
        ("content_hash", "sha256:" + "A" * 64),
        ("observed_at", "2026-09-11T00:00:00"),
        ("valid_from", "not-a-date"),
        ("valid_until", 42),
    ],
)
def test_knowledge_check_rejects_malformed_provenance(field, value):
    record = _node("Fact", "fact-a", **{field: value})

    with pytest.raises(StructuredError) as error:
        check_knowledge(_snapshot([record]), _snapshot())

    assert error.value.code == "INVALID_PROVENANCE"
    assert error.value.details == {"field": field, "record": "current node 0"}


def test_knowledge_check_reports_deterministic_snapshot_diff():
    baseline = _snapshot([_node("Artifact", "a", title="old")])
    current = _snapshot([_node("Artifact", "a", title="new"), _node("Fact", "f")])

    report = check_knowledge(current, baseline)

    assert report.valid is False
    assert list(report.issues) == []
    assert report.to_dict()["diff"] == {
        "nodes": {
            "added": [_node("Fact", "f")],
            "removed": [],
            "changed": [{"before": _node("Artifact", "a", title="old"),
                         "after": _node("Artifact", "a", title="new")}],
        },
        "relationships": {"added": [], "removed": [], "changed": []},
    }


def test_knowledge_check_reports_duplicate_and_orphan_integrity_issues():
    current = _snapshot(
        [_node("Artifact", "a"), _node("Artifact", "a")],
        [_relationship("r", "a", "missing")],
    )

    report = check_knowledge(current, _snapshot())

    assert report.valid is False
    assert list(report.issues) == [
        {"code": "DUPLICATE_NODE", "message": "Node key is duplicated",
         "details": {"kind": "Artifact", "key": "a"}},
        {"code": "ORPHAN_RELATIONSHIP", "message": "Relationship endpoint is missing",
         "details": {"key": "r", "missing": [{"kind": "Artifact", "key": "missing"}]}},
    ]


def test_knowledge_check_reports_duplicate_relationship_keys():
    current = _snapshot(
        [_node("Artifact", "a"), _node("Artifact", "b")],
        [_relationship("r", "a", "b"), _relationship("r", "a", "b")],
    )

    report = check_knowledge(current, _snapshot())

    assert list(report.issues) == [
        {"code": "DUPLICATE_RELATIONSHIP", "message": "Relationship key is duplicated",
         "details": {"key": "r"}},
    ]


def test_knowledge_check_rejects_duplicate_records_in_baseline():
    snapshot = _snapshot([_node("Artifact", "a")])
    baseline = _snapshot([_node("Artifact", "a"), _node("Artifact", "a")])

    report = check_knowledge(snapshot, baseline)

    assert report.valid is False
    assert list(report.issues) == [
        {"code": "DUPLICATE_NODE", "message": "Node key is duplicated",
         "details": {"kind": "Artifact", "key": "a", "snapshot": "baseline"}},
    ]


@pytest.mark.parametrize("snapshot", [
    _snapshot([{"kind": "Artifact", "properties": {}}]),
    _snapshot([{"kind": "Artifact", "key": [] , "properties": {}}]),
    _snapshot([], [{"key": "r", "source_kind": "Artifact", "source_key": "a",
                    "target_kind": "Artifact", "target_key": "b"}]),
])
def test_knowledge_check_rejects_malformed_snapshot(snapshot):
    with pytest.raises(StructuredError) as error:
        check_knowledge(snapshot, _snapshot())

    assert error.value.code == "INVALID_KNOWLEDGE"


def test_build_knowledge_snapshot_matches_projection_and_is_deterministic():
    dataset = Path("data/coder_activation.json")

    snapshot = build_knowledge_snapshot(dataset)

    assert snapshot == projection_to_snapshot(build_graph_projection(dataset))
    assert snapshot == build_knowledge_snapshot(dataset)
    assert snapshot["nodes"][0]["kind"] == "Dataset"


def test_strict_policy_blocks_drift_and_classifies_it_as_warning():
    report = check_knowledge(_snapshot([_node("Fact", "new")]), _snapshot())

    assert evaluate_knowledge_policy(report, {"mode": "strict"}) == {
        "mode": "strict", "allowed": False, "severity": "warning"
    }


def test_report_only_policy_allows_invalid_knowledge_without_hiding_report():
    report = check_knowledge(_snapshot([_node("Fact", "new")]), _snapshot())

    assert report.valid is False
    assert evaluate_knowledge_policy(report, {"mode": "report-only"}) == {
        "mode": "report-only", "allowed": True, "severity": "warning"
    }


def test_allowlist_policy_allows_exact_declared_drift():
    current = _snapshot([_node("Fact", "new")])
    report = check_knowledge(current, _snapshot())

    assert evaluate_knowledge_policy(report, {
        "mode": "allowlist",
        "allowlist": {"nodes": {"added": [_node("Fact", "new")]}}
    }) == {"mode": "allowlist", "allowed": True, "severity": "none"}
