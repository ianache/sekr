from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sekr.freshness import evaluate_freshness


AS_OF = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def test_evaluate_freshness_assigns_all_states_and_uses_precedence(tmp_path):
    """Changing the hash comparison must fail this state and precedence contract."""
    (tmp_path / "current.md").write_bytes(b"current evidence")
    (tmp_path / "changed.md").write_bytes(b"changed evidence")
    (tmp_path / "stale.md").write_bytes(b"stale evidence")
    snapshot = {
        "nodes": [
            {
                "kind": "Fact",
                "key": "current",
                "properties": {
                    "evidence": ["current.md"],
                    "content_hash": _hash(b"current evidence"),
                    "valid_from": "2026-09-01T00:00:00Z",
                    "valid_until": "2026-09-12T00:00:00Z",
                },
            },
            {
                "kind": "Fact",
                "key": "changed",
                "properties": {
                    "evidence": ["changed.md"],
                    "content_hash": _hash(b"old evidence"),
                    "valid_until": "2020-01-01T00:00:00Z",
                },
            },
            {
                "kind": "Fact",
                "key": "stale",
                "properties": {
                    "evidence": ["stale.md"],
                    "content_hash": _hash(b"stale evidence"),
                    "valid_until": "2020-01-01T00:00:00Z",
                },
            },
            {
                "kind": "Fact",
                "key": "unverified",
                "properties": {
                    "evidence": ["missing.md"],
                    "content_hash": _hash(b"missing evidence"),
                },
            },
            {
                "kind": "Fact",
                "key": "conflicted",
                "properties": {
                    "confidence": "CONFLICTED",
                    "evidence": ["missing.md"],
                },
            },
        ],
        "relationships": [],
    }

    report = evaluate_freshness(snapshot, AS_OF, tmp_path)

    assert report.to_dict() == {
        "as_of": "2026-09-11T12:00:00Z",
        "valid": False,
        "counts": {
            "conflicted": 1,
            "unverified": 1,
            "changed": 1,
            "stale": 1,
            "current": 1,
        },
        "records": [
            {"kind": "Fact", "key": "changed", "state": "changed", "reasons": ["CONTENT_HASH_MISMATCH"]},
            {"kind": "Fact", "key": "conflicted", "state": "conflicted", "reasons": ["EXPLICIT_CONFLICT"]},
            {"kind": "Fact", "key": "current", "state": "current", "reasons": []},
            {"kind": "Fact", "key": "stale", "state": "stale", "reasons": ["VALIDITY_EXPIRED"]},
            {"kind": "Fact", "key": "unverified", "state": "unverified", "reasons": ["EVIDENCE_UNREADABLE"]},
        ],
    }


def test_evaluate_freshness_marks_incompatible_dates_conflicted_and_confines_evidence(tmp_path):
    """Removing the validity conflict or root check must fail these observable states."""
    outside = tmp_path.parent / "outside.md"
    outside.write_bytes(b"outside evidence")
    snapshot = {
        "nodes": [
            {
                "kind": "Fact",
                "key": "bad-window",
                "properties": {
                    "valid_from": "2026-09-12T00:00:00Z",
                    "valid_until": "2026-09-11T00:00:00Z",
                },
            },
            {
                "kind": "Fact",
                "key": "outside-root",
                "properties": {
                    "evidence": ["../outside.md"],
                    "content_hash": _hash(b"outside evidence"),
                },
            },
        ],
        "relationships": [],
    }

    report = evaluate_freshness(snapshot, AS_OF, tmp_path)

    assert report.records == (
        {"kind": "Fact", "key": "bad-window", "state": "conflicted", "reasons": ["INCOMPATIBLE_VALIDITY_WINDOW"]},
        {"kind": "Fact", "key": "outside-root", "state": "unverified", "reasons": ["EVIDENCE_UNREADABLE"]},
    )


def test_evaluate_freshness_marks_explicit_stale_confidence_stale_when_hash_matches(tmp_path):
    """Removing explicit stale handling must not classify matching evidence as current."""
    (tmp_path / "source.md").write_bytes(b"matching evidence")
    snapshot = {
        "nodes": [
            {
                "kind": "Fact",
                "key": "explicit-stale",
                "properties": {
                    "confidence": "STALE",
                    "evidence": ["source.md"],
                    "content_hash": _hash(b"matching evidence"),
                },
            }
        ],
        "relationships": [],
    }

    report = evaluate_freshness(snapshot, AS_OF, tmp_path)

    assert report.records[0]["state"] == "stale"


def test_evaluate_freshness_hashes_line_range_evidence_reference(tmp_path):
    """Passing a line-range reference unchanged must not make readable evidence unverified."""
    (tmp_path / "source.md").write_bytes(b"line-range evidence")
    snapshot = {
        "nodes": [
            {
                "kind": "Fact",
                "key": "line-range-evidence",
                "properties": {
                    "evidence": ["source.md:1-1"],
                    "content_hash": _hash(b"line-range evidence"),
                },
            }
        ],
        "relationships": [],
    }

    report = evaluate_freshness(snapshot, AS_OF, tmp_path)

    assert report.records[0]["state"] == "current"


def test_evaluate_freshness_is_deterministic_and_sorts_node_and_relationship_records(tmp_path):
    """Changing record sort order or repeatability must fail this report comparison."""
    (tmp_path / "evidence.md").write_bytes(b"evidence")
    snapshot = {
        "nodes": [
            {"kind": "Fact", "key": "z", "properties": {}},
            {
                "kind": "Fact",
                "key": "a",
                "properties": {
                    "evidence": ["evidence.md"],
                    "content_hash": _hash(b"evidence"),
                },
            },
        ],
        "relationships": [
            {"key": "relation.z", "properties": {}},
            {
                "key": "relation.a",
                "properties": {
                    "evidence": ["evidence.md"],
                    "content_hash": _hash(b"evidence"),
                },
            },
        ],
    }

    first = evaluate_freshness(snapshot, AS_OF, tmp_path).to_dict()
    second = evaluate_freshness(snapshot, AS_OF, tmp_path).to_dict()

    assert first == second
    assert [(record["kind"], record["key"]) for record in first["records"]] == [
        ("Fact", "a"),
        ("Fact", "z"),
        ("Relationship", "relation.a"),
        ("Relationship", "relation.z"),
    ]
