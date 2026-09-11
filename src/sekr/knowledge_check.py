"""Deterministic integrity and baseline checks for knowledge snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from sekr.errors import StructuredError
from sekr.ingest import GraphProjection


Snapshot = Mapping[str, object]


@dataclass(frozen=True)
class KnowledgeCheckReport:
    valid: bool
    issues: tuple[dict[str, object], ...]
    diff: dict[str, dict[str, list[dict[str, object]]]]

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "issues": list(self.issues), "diff": self.diff}


def projection_to_snapshot(projection: GraphProjection) -> dict[str, object]:
    """Convert a validated graph projection to the canonical check format."""
    nodes = (projection.dataset, *projection.nodes)
    return {
        "nodes": [
            {"kind": node.kind, "key": node.key, "properties": dict(node.properties)}
            for node in nodes
        ],
        "relationships": [
            {
                "key": relationship.key,
                "source_kind": relationship.source_kind,
                "source_key": relationship.source_key,
                "target_kind": relationship.target_kind,
                "target_key": relationship.target_key,
                "properties": dict(relationship.properties),
            }
            for relationship in projection.relationships
        ],
    }


def build_knowledge_snapshot(path: str) -> dict[str, object]:
    """Build a validated, canonical snapshot from a SEKR dataset JSON file."""
    from sekr.ingest import build_graph_projection

    return projection_to_snapshot(build_graph_projection(path))


def check_knowledge(current: Snapshot, baseline: Snapshot) -> KnowledgeCheckReport:
    """Check integrity and compare a current snapshot against its baseline."""
    current_nodes, current_relationships = _snapshot_records(current, "current")
    baseline_nodes, baseline_relationships = _snapshot_records(baseline, "baseline")
    issues = _integrity_issues(current_nodes, current_relationships, "current")
    issues.extend(_integrity_issues(baseline_nodes, baseline_relationships, "baseline"))
    diff = {
        "nodes": _diff_records(current_nodes, baseline_nodes, "kind", "key"),
        "relationships": _diff_records(current_relationships, baseline_relationships, "key"),
    }
    has_diff = any(diff[group][kind] for group in diff for kind in diff[group])
    return KnowledgeCheckReport(not issues and not has_diff, tuple(issues), diff)


def evaluate_knowledge_policy(
    report: KnowledgeCheckReport, policy: Mapping[str, object] | None = None
) -> dict[str, object]:
    """Return whether a report is permitted by a strict, report-only, or allowlist policy."""
    policy = policy or {"mode": "strict"}
    mode = policy.get("mode", "strict")
    if mode not in {"strict", "report-only", "allowlist"}:
        raise StructuredError("INVALID_POLICY", "Knowledge policy mode is invalid")
    if mode == "report-only":
        allowed = True
        severity = _report_severity(report)
    elif mode == "strict":
        allowed = report.valid
        severity = _report_severity(report)
    else:
        allowlist = policy.get("allowlist", {})
        if not isinstance(allowlist, dict):
            raise StructuredError("INVALID_POLICY", "Knowledge policy allowlist must be an object")
        remaining = _unallowed_diff(report.diff, allowlist)
        allowed = not report.issues and not any(
            remaining[group][kind] for group in remaining for kind in remaining[group]
        )
        severity = "critical" if report.issues else ("warning" if not allowed else "none")
    return {"mode": mode, "allowed": allowed, "severity": severity}


def _report_severity(report: KnowledgeCheckReport) -> str:
    if report.issues:
        return "critical"
    return "warning" if any(report.diff[group][kind] for group in report.diff for kind in report.diff[group]) else "none"


def _unallowed_diff(
    diff: dict[str, dict[str, list[dict[str, object]]]], allowlist: dict[str, object]
) -> dict[str, dict[str, list[dict[str, object]]]]:
    remaining: dict[str, dict[str, list[dict[str, object]]]] = {}
    for group, categories in diff.items():
        configured = allowlist.get(group, {})
        if not isinstance(configured, dict):
            raise StructuredError("INVALID_POLICY", "Knowledge policy allowlist entries must be objects")
        remaining[group] = {}
        for category, records in categories.items():
            allowed = configured.get(category, [])
            if not isinstance(allowed, list):
                raise StructuredError("INVALID_POLICY", "Knowledge policy allowlist records must be arrays")
            allowed_keys = {_canonical(record) for record in allowed}
            remaining[group][category] = [
                record for record in records
                if _canonical(record) not in allowed_keys
            ]
    return remaining


def _snapshot_records(
    snapshot: Snapshot, label: str
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    nodes = snapshot.get("nodes", [])
    relationships = snapshot.get("relationships", [])
    if not isinstance(nodes, list) or not isinstance(relationships, list):
        raise StructuredError(
            "INVALID_KNOWLEDGE", f"{label.capitalize()} snapshot has invalid records"
        )
    if not all(isinstance(record, dict) for record in (*nodes, *relationships)):
        raise StructuredError(
            "INVALID_KNOWLEDGE", f"{label.capitalize()} snapshot records must be objects"
        )
    for index, node in enumerate(nodes):
        _require_fields(node, ("kind", "key", "properties"), f"{label} node {index}")
        if not isinstance(node["kind"], str) or not node["kind"]:
            raise StructuredError("INVALID_KNOWLEDGE", f"{label.capitalize()} node kind must be a non-empty string")
        if not isinstance(node["key"], str) or not node["key"]:
            raise StructuredError("INVALID_KNOWLEDGE", f"{label.capitalize()} node key must be a non-empty string")
        if not isinstance(node["properties"], dict):
            raise StructuredError("INVALID_KNOWLEDGE", f"{label.capitalize()} node properties must be an object")
    for index, relationship in enumerate(relationships):
        _require_fields(
            relationship,
            ("key", "source_kind", "source_key", "target_kind", "target_key", "properties"),
            f"{label} relationship {index}",
        )
        for field in ("key", "source_kind", "source_key", "target_kind", "target_key"):
            if not isinstance(relationship[field], str) or not relationship[field]:
                raise StructuredError("INVALID_KNOWLEDGE", f"{label.capitalize()} relationship {field} must be a non-empty string")
        if not isinstance(relationship["properties"], dict):
            raise StructuredError("INVALID_KNOWLEDGE", f"{label.capitalize()} relationship properties must be an object")
    return list(nodes), list(relationships)


def _require_fields(record: Mapping[str, object], fields: tuple[str, ...], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise StructuredError(
            "INVALID_KNOWLEDGE", f"{label.capitalize()} is missing required fields", {"missing": missing}
        )


def _integrity_issues(
    nodes: list[dict[str, object]], relationships: list[dict[str, object]], snapshot: str
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    node_counts: dict[tuple[object, object], int] = {}
    node_keys: set[tuple[object, object]] = set()
    for node in nodes:
        identity = (node.get("kind"), node.get("key"))
        node_counts[identity] = node_counts.get(identity, 0) + 1
        node_keys.add(identity)
    for kind, key in sorted(
        (identity for identity, count in node_counts.items() if count > 1),
        key=lambda value: (str(value[0]), str(value[1])),
    ):
        details = {"kind": kind, "key": key}
        if snapshot == "baseline":
            details["snapshot"] = snapshot
        issues.append({
            "code": "DUPLICATE_NODE",
            "message": "Node key is duplicated",
            "details": details,
        })

    relationship_counts: dict[object, int] = {}
    for relationship in relationships:
        key = relationship.get("key")
        relationship_counts[key] = relationship_counts.get(key, 0) + 1
    for key in sorted(
        (key for key, count in relationship_counts.items() if count > 1),
        key=lambda value: str(value),
    ):
        details = {"key": key}
        if snapshot == "baseline":
            details["snapshot"] = snapshot
        issues.append({
            "code": "DUPLICATE_RELATIONSHIP",
            "message": "Relationship key is duplicated",
            "details": details,
        })

    for relationship in relationships:
        missing = []
        for kind_field, key_field in (
            ("source_kind", "source_key"), ("target_kind", "target_key")
        ):
            identity = (relationship.get(kind_field), relationship.get(key_field))
            if identity not in node_keys:
                missing.append({"kind": identity[0], "key": identity[1]})
        if missing:
            details = {"key": relationship.get("key"), "missing": missing}
            if snapshot == "baseline":
                details["snapshot"] = snapshot
            issues.append({
                "code": "ORPHAN_RELATIONSHIP",
                "message": "Relationship endpoint is missing",
                "details": details,
            })
    return issues


def _diff_records(
    current: list[dict[str, object]], baseline: list[dict[str, object]], *identity_fields: str
) -> dict[str, list[dict[str, object]]]:
    current_by_id = {_identity(record, identity_fields): record for record in current}
    baseline_by_id = {_identity(record, identity_fields): record for record in baseline}
    added = [current_by_id[key] for key in current_by_id.keys() - baseline_by_id.keys()]
    removed = [baseline_by_id[key] for key in baseline_by_id.keys() - current_by_id.keys()]
    changed = [
        {"before": baseline_by_id[key], "after": current_by_id[key]}
        for key in current_by_id.keys() & baseline_by_id.keys()
        if _canonical(current_by_id[key]) != _canonical(baseline_by_id[key])
    ]
    return {
        "added": _sorted_records(added),
        "removed": _sorted_records(removed),
        "changed": sorted(changed, key=lambda item: _canonical(item["before"])),
    }


def _identity(record: Mapping[str, object], fields: tuple[str, ...]) -> tuple[object, ...]:
    return tuple(record.get(field) for field in fields)


def _sorted_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(records, key=_canonical)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
