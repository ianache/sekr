"""Deterministic, read-only provenance freshness evaluation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from sekr.errors import StructuredError
from sekr.provenance import is_strict_utc_timestamp, validate_provenance


_STATES = ("conflicted", "unverified", "changed", "stale", "current")


@dataclass(frozen=True)
class FreshnessReport:
    """A stable freshness assessment for a canonical knowledge snapshot."""

    as_of: datetime
    records: tuple[dict[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        counts = {state: 0 for state in _STATES}
        for record in self.records:
            counts[str(record["state"])] += 1
        return {
            "as_of": _format_datetime(self.as_of),
            "valid": all(record["state"] == "current" for record in self.records),
            "counts": counts,
            "records": [dict(record) for record in self.records],
        }


def evaluate_freshness(
    snapshot: Mapping[str, object], as_of: datetime, root: Path | str,
    *, allow_legacy_null_valid_from: bool = False,
) -> FreshnessReport:
    """Evaluate snapshot provenance without executing or modifying evidence files."""
    _validate_snapshot_provenance(snapshot, allow_legacy_null_valid_from=allow_legacy_null_valid_from)
    root_path = Path(root).resolve()
    records = [
        _evaluate_record(kind, key, properties, as_of, root_path)
        for kind, key, properties in _snapshot_records(snapshot)
    ]
    return FreshnessReport(
        as_of=as_of,
        records=tuple(sorted(records, key=lambda record: (str(record["kind"]), str(record["key"])))),
    )


def _validate_snapshot_provenance(snapshot: Mapping[str, object], *, allow_legacy_null_valid_from: bool = False) -> None:
    if not isinstance(snapshot, Mapping):
        raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot must be an object")
    for collection in ("nodes", "relationships"):
        records = snapshot.get(collection)
        if not isinstance(records, list):
            raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot records must be arrays")
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot records must be objects")
            required = (("kind", "key", "properties") if collection == "nodes" else ("key", "source_kind", "source_key", "target_kind", "target_key", "properties"))
            missing = [field for field in required if field not in record]
            if missing:
                raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot record is missing required fields", {"collection": collection, "index": index, "missing": missing})
            identity_fields = required[:-1]
            for field in identity_fields:
                if field not in record:
                    continue
                if not isinstance(record[field], str) or not record[field]:
                    raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot record identity fields must be non-empty strings", {"collection": collection, "index": index, "field": field})
            properties = record.get("properties")
            if not isinstance(properties, Mapping):
                raise StructuredError("INVALID_KNOWLEDGE", "Knowledge snapshot record properties must be an object")
            validate_provenance(
                properties,
                f"snapshot {'node' if collection == 'nodes' else 'relationship'} {index}",
                allow_legacy_null_valid_from=allow_legacy_null_valid_from,
                allow_legacy_null_evidence=collection == "relationships" and properties.get("relation_type") in {
                    "HAS_ARTIFACT", "HAS_FACT", "HAS_PROFILE", "EXPECTS_ARTIFACT"
                },
            )


def _snapshot_records(snapshot: Mapping[str, object]) -> list[tuple[str, str, Mapping[str, object]]]:
    records: list[tuple[str, str, Mapping[str, object]]] = []
    nodes = snapshot.get("nodes", [])
    relationships = snapshot.get("relationships", [])
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, Mapping):
                records.append(
                    (
                        str(node.get("kind", "Node")),
                        str(node.get("key", "")),
                        _properties(node),
                    )
                )
    if isinstance(relationships, list):
        for relationship in relationships:
            if isinstance(relationship, Mapping):
                records.append(("Relationship", str(relationship.get("key", "")), _properties(relationship)))
    return records


def _properties(record: Mapping[str, object]) -> Mapping[str, object]:
    properties = record.get("properties", {})
    return properties if isinstance(properties, Mapping) else {}


def _evaluate_record(
    kind: str, key: str, properties: Mapping[str, object], as_of: datetime, root: Path
) -> dict[str, object]:
    state, reasons = _record_state(properties, as_of, root)
    return {"kind": kind, "key": key, "state": state, "reasons": reasons}


def _record_state(
    properties: Mapping[str, object], as_of: datetime, root: Path
) -> tuple[str, list[str]]:
    valid_from = _parse_datetime(properties.get("valid_from"))
    valid_until = _parse_datetime(properties.get("valid_until"))
    if properties.get("confidence") == "CONFLICTED":
        return "conflicted", ["EXPLICIT_CONFLICT"]
    if valid_from is not None and valid_until is not None and valid_from > valid_until:
        return "conflicted", ["INCOMPATIBLE_VALIDITY_WINDOW"]

    evidence = _evidence_files(properties.get("evidence"), root)
    content_hash = properties.get("content_hash")
    if evidence is None or not isinstance(content_hash, str):
        return "unverified", ["EVIDENCE_UNREADABLE"]

    hashes = [_hash_file(path) for path in evidence]
    if any(digest is None for digest in hashes):
        return "unverified", ["EVIDENCE_UNREADABLE"]
    if any(digest != content_hash for digest in hashes):
        return "changed", ["CONTENT_HASH_MISMATCH"]

    if properties.get("confidence") == "STALE" or properties.get("freshness") == "stale":
        return "stale", ["EXPLICIT_STALE"]
    if valid_until is not None and valid_until < _utc(as_of):
        return "stale", ["VALIDITY_EXPIRED"]
    if valid_from is not None and valid_from > _utc(as_of):
        return "stale", ["VALIDITY_NOT_ACTIVE"]
    return "current", []


def _evidence_files(value: object, root: Path) -> tuple[Path, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    files: list[Path] = []
    for reference in value:
        if not isinstance(reference, str):
            return None
        candidate = _resolve_evidence(reference, root)
        if candidate is None:
            return None
        files.append(candidate)
    return tuple(files)


def _resolve_evidence(reference: str, root: Path) -> Path | None:
    candidate = Path(_evidence_path(reference))
    if candidate.is_absolute():
        return None
    try:
        resolved = (root / candidate).resolve()
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _evidence_path(reference: str) -> str:
    """Return the file component of a path or terminal ``:start-end`` reference."""
    path, separator, line_range = reference.rpartition(":")
    if separator and path and _is_line_range(line_range):
        return path
    return reference


def _is_line_range(value: str) -> bool:
    start, separator, end = value.partition("-")
    return bool(separator and start and end and start.isdecimal() and end.isdecimal())


def _hash_file(path: Path) -> str | None:
    try:
        return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    except OSError:
        return None


def _parse_datetime(value: object) -> datetime | None:
    if not is_strict_utc_timestamp(value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return _utc(parsed)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _format_datetime(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
