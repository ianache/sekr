"""SQLite storage and deterministic candidate retrieval for SEKR v0.1."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from sekr.errors import StructuredError
from sekr.models import Artifact, DatasetMetadata, KnowledgeFact, Relation, TaskProfile


_ARTIFACT_TYPES = (
    "feature",
    "symbol",
    "endpoint",
    "table",
    "test",
    "requirement",
    "component",
    "adr",
    "document",
    "fact",
    "repository",
)
_CONFIDENCES = ("VERIFIED", "APPROVED", "INFERRED", "STALE", "CONFLICTED", "UNKNOWN")
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    artifact_count: int
    errors: tuple[StructuredError, ...] = ()


@dataclass(frozen=True)
class SearchCandidate:
    artifact: Artifact
    score_evidence: tuple[str, ...]

    def __iter__(self) -> Iterator[object]:
        """Allow callers to unpack a candidate as ``(Artifact, score_evidence)``."""
        yield self.artifact
        yield self.score_evidence


def normalize_tokens(values: Iterable[str]) -> tuple[str, ...]:
    """Return ordered, lowercase alphanumeric tokens without duplicates."""
    tokens: list[str] = []
    seen: set[str] = set()
    for value in values:
        for token in _TOKEN_PATTERN.findall(value.lower()):
            if token not in seen:
                seen.add(token)
                tokens.append(token)
    return tuple(tokens)


def _connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(path: str | Path) -> None:
    """Create the local v0.1 SQLite schema if it is not already present."""
    artifact_types = ", ".join(repr(value) for value in _ARTIFACT_TYPES)
    confidences = ", ".join(repr(value) for value in _CONFIDENCES)
    with _connect(path) as connection:
        connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                artifact_type TEXT NOT NULL CHECK (artifact_type IN ({artifact_types})),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                path TEXT,
                evidence_json TEXT NOT NULL,
                confidence TEXT NOT NULL CHECK (confidence IN ({confidences})),
                CHECK (confidence IN ('UNKNOWN', 'CONFLICTED') OR evidence_json <> '[]')
            );
            CREATE TABLE IF NOT EXISTS relations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES artifacts(id),
                target_id TEXT NOT NULL REFERENCES artifacts(id),
                relation_type TEXT NOT NULL,
                evidence_json TEXT NOT NULL,
                confidence TEXT NOT NULL CHECK (confidence IN ({confidences})),
                CHECK (confidence IN ('UNKNOWN', 'CONFLICTED') OR evidence_json <> '[]')
            );
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                artifact_id TEXT REFERENCES artifacts(id),
                statement TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                evidence_json TEXT NOT NULL,
                confidence TEXT NOT NULL CHECK (confidence IN ({confidences})),
                freshness TEXT,
                source_version TEXT NOT NULL DEFAULT '',
                valid_from TEXT,
                scope TEXT NOT NULL DEFAULT '',
                owner TEXT,
                CHECK (confidence IN ('UNKNOWN', 'CONFLICTED') OR evidence_json <> '[]')
            );
            CREATE TABLE IF NOT EXISTS task_profiles (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                terms_json TEXT NOT NULL,
                expected_artifact_types_json TEXT NOT NULL,
                expected_artifacts_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dataset_metadata (
                version TEXT PRIMARY KEY,
                source_commit TEXT NOT NULL DEFAULT '',
                generated_at TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT ''
            );
            """
        )


def _read_dataset(dataset_json: str | Path) -> dict[str, object]:
    try:
        return json.loads(Path(dataset_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StructuredError("INVALID_DATASET", "Dataset JSON could not be read", {"error": str(error)}) from error


def _require_provenance(identifier: str, evidence: Sequence[str], confidence: str) -> None:
    _require_string_list(evidence, "evidence", "INVALID_EVIDENCE", identifier)
    if not evidence and confidence not in {"UNKNOWN", "CONFLICTED"}:
        raise StructuredError(
            "MISSING_PROVENANCE",
            f"{identifier} requires source evidence for {confidence} confidence",
            {"id": identifier, "confidence": confidence},
        )


def _require_text(value: object, field: str, code: str, identifier: object = None) -> None:
    if not isinstance(value, str) or not value.strip():
        raise StructuredError(code, f"{field} must be non-blank text", {"id": identifier, "field": field})


def _require_string_list(value: object, field: str, code: str, identifier: object) -> None:
    if not isinstance(value, (list, tuple)) or any(not isinstance(entry, str) or not entry.strip() for entry in value):
        raise StructuredError(code, f"{field} must contain only non-blank strings", {"id": identifier, "field": field})


def _validate_raw_dataset(data: dict[str, object]) -> None:
    """Check data that model normalization or SQLite constraints would obscure."""
    metadata = data["metadata"]
    for field in ("version", "source_commit", "generated_at"):
        _require_text(metadata.get(field), field, "INVALID_METADATA")
    required_fields = {
        "artifacts": ("id", "artifact_type", "title"),
        "relations": ("id", "source_id", "target_id", "relation_type"),
        "facts": ("id", "statement"),
        "task_profiles": ("id", "name"),
    }
    for collection, fields in required_fields.items():
        if not isinstance(data[collection], list):
            raise StructuredError("INVALID_DATASET", f"{collection} must be a list")
        for record in data[collection]:
            for field in fields:
                _require_text(record.get(field), field, "INVALID_DATASET", record.get("id"))
            if collection in {"artifacts", "relations", "facts"}:
                if record.get("confidence", "UNKNOWN") not in _CONFIDENCES:
                    raise StructuredError("INVALID_CONFIDENCE", "Unsupported confidence", {"id": record["id"]})
            if collection == "artifacts":
                if record["artifact_type"] not in _ARTIFACT_TYPES:
                    raise StructuredError("INVALID_ARTIFACT_TYPE", "Unsupported artifact type", {"id": record["id"]})
                if not isinstance(record.get("description", ""), str) or not isinstance(record.get("path") or "", str):
                    raise StructuredError("INVALID_DATASET", "Artifact description and path must be text", {"id": record["id"]})
            if collection == "task_profiles":
                for field in ("terms", "expected_artifact_types", "expected_artifacts"):
                    _require_string_list(record.get(field, ()), field, "INVALID_TASK_PROFILE", record["id"])
                for artifact_type in record.get("expected_artifact_types", ()):
                    if artifact_type not in _ARTIFACT_TYPES:
                        raise StructuredError("INVALID_ARTIFACT_TYPE", "Unsupported task profile artifact type", {"id": record["id"]})
    records = (
        ("artifacts", data["artifacts"]),
        ("relations", data["relations"]),
        ("facts", data["facts"]),
    )
    for record_type, collection in records:
        for record in collection:
            _require_provenance(
                record.get("id", f"{record_type} record"),
                record.get("evidence", ()),
                record.get("confidence", "UNKNOWN"),
            )

    artifact_ids = {record["id"] for record in data["artifacts"]}
    references: list[tuple[str, str, str]] = []
    for record in data["relations"]:
        references.extend(
            ((record["id"], "source_id", record["source_id"]), (record["id"], "target_id", record["target_id"]))
        )
    for record in data["facts"]:
        if record.get("artifact_id") is not None:
            references.append((record["id"], "artifact_id", record["artifact_id"]))
    for record in data["task_profiles"]:
        references.extend((record["id"], "expected_artifacts", reference) for reference in record.get("expected_artifacts", ()))
    for record_id, field, reference in references:
        if not isinstance(reference, str) or not reference.strip() or reference not in artifact_ids:
            raise StructuredError(
                "INVALID_REFERENCE",
                f"{record_id} references an artifact that is not present",
                {"id": record_id, "field": field, "reference": reference},
            )


def validate_dataset_json(data: dict[str, object]) -> None:
    """Raise a structured error when a raw JSON dataset violates SEKR rules."""
    try:
        _validate_raw_dataset(data)
    except StructuredError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise StructuredError(
            "INVALID_DATASET", "Dataset has invalid records", {"error": str(error)}
        ) from error


def load_dataset(path: str | Path, dataset_json: str | Path) -> None:
    """Replace database contents with a checked, curated JSON dataset."""
    data = _read_dataset(dataset_json)
    try:
        validate_dataset_json(data)
        metadata = DatasetMetadata(**data["metadata"])
        artifacts = [Artifact(**item) for item in data["artifacts"]]
        relations = [Relation(**item) for item in data["relations"]]
        fact_records = data["facts"]
        facts = [
            KnowledgeFact(**{key: value for key, value in item.items() if key != "artifact_id"})
            for item in fact_records
        ]
        profiles = [TaskProfile(**item) for item in data["task_profiles"]]
    except StructuredError:
        raise
    except (AttributeError, KeyError, TypeError) as error:
        raise StructuredError("INVALID_DATASET", "Dataset has invalid records", {"error": str(error)}) from error

    init_db(path)
    try:
        with _connect(path) as connection:
            connection.execute("DELETE FROM relations")
            connection.execute("DELETE FROM facts")
            connection.execute("DELETE FROM task_profiles")
            connection.execute("DELETE FROM artifacts")
            connection.execute("DELETE FROM dataset_metadata")
            connection.executemany(
                "INSERT INTO artifacts VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(item.id, item.artifact_type, item.title, item.description, item.path, json.dumps(list(item.evidence)), item.confidence) for item in artifacts],
            )
            connection.executemany(
                "INSERT INTO relations VALUES (?, ?, ?, ?, ?, ?)",
                [(item.id, item.source_id, item.target_id, item.relation_type, json.dumps(list(item.evidence)), item.confidence) for item in relations],
            )
            connection.executemany(
                "INSERT INTO facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(item.id, record.get("artifact_id"), item.statement, item.source, json.dumps(list(item.evidence)), item.confidence, item.freshness, item.source_version, item.valid_from, item.scope, item.owner) for item, record in zip(facts, fact_records, strict=True)],
            )
            connection.executemany(
                "INSERT INTO task_profiles VALUES (?, ?, ?, ?, ?)",
                [(item.id, item.name, json.dumps(list(item.terms)), json.dumps(list(item.expected_artifact_types)), json.dumps(list(item.expected_artifacts))) for item in profiles],
            )
            connection.execute("INSERT INTO dataset_metadata VALUES (?, ?, ?, ?)", (metadata.version, metadata.source_commit, metadata.generated_at, metadata.description))
    except sqlite3.IntegrityError as error:
        raise StructuredError("INVALID_DATASET", "Dataset violates SQLite constraints", {"error": str(error)}) from error


def validate_dataset(path: str | Path) -> ValidationResult:
    """Return validation failures as structured errors rather than raising them."""
    errors: list[StructuredError] = []
    artifact_count = 0
    try:
        with _connect(path) as connection:
            artifact_count = connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0]
            metadata_rows = connection.execute("SELECT * FROM dataset_metadata ORDER BY version").fetchall()
            if not metadata_rows:
                errors.append(StructuredError("MISSING_METADATA", "Dataset metadata is required"))
            elif len(metadata_rows) != 1:
                errors.append(StructuredError("INVALID_METADATA", "Dataset must have exactly one metadata record"))
            data = {"metadata": dict(metadata_rows[0]) if metadata_rows else {}}
            for table in ("artifacts", "relations", "facts", "task_profiles"):
                records = []
                for row in connection.execute(f"SELECT * FROM {table} ORDER BY id"):
                    record = dict(row)
                    for field in tuple(record):
                        if field.endswith("_json"):
                            try:
                                record[field[:-5]] = json.loads(record.pop(field))
                            except (TypeError, ValueError) as error:
                                code = "INVALID_TASK_PROFILE" if table == "task_profiles" else "INVALID_EVIDENCE"
                                raise StructuredError(code, "Record contains invalid JSON", {"id": record["id"], "field": field}) from error
                    records.append(record)
                data[table] = records
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if metadata_rows:
            _validate_raw_dataset(data)
    except StructuredError as error:
        errors.append(error)
        return ValidationResult(False, artifact_count, tuple(errors))
    except sqlite3.Error as error:
        return ValidationResult(False, artifact_count, (StructuredError("INVALID_DATABASE", str(error)),))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        return ValidationResult(False, artifact_count, (StructuredError("INVALID_DATASET", "Dataset has invalid records", {"error": str(error)}),))
    if artifact_count == 0:
        errors.append(StructuredError("EMPTY_DATASET", "Dataset must contain artifacts"))
    errors.extend(
        StructuredError("INVALID_REFERENCE", "Database foreign key reference is invalid", {"table": row[0], "rowid": row[1], "parent": row[2]})
        for row in foreign_key_errors
    )
    return ValidationResult(not errors, artifact_count, tuple(errors))


class KnowledgeRepository:
    """Read-only candidate search over the local context-compiler dataset."""

    def __init__(self, path: str | Path) -> None:
        self.path = path

    def search_candidates(self, tokens: Iterable[str]) -> list[SearchCandidate]:
        query_tokens = set(normalize_tokens(tokens))
        if not query_tokens:
            return []
        with _connect(self.path) as connection:
            rows = connection.execute("SELECT * FROM artifacts ORDER BY id").fetchall()
            relations = connection.execute("SELECT * FROM relations ORDER BY id").fetchall()
            profiles = connection.execute("SELECT * FROM task_profiles ORDER BY id").fetchall()

        scores: dict[str, int] = {}
        evidence: dict[str, list[str]] = {}
        for row in rows:
            text = " ".join((row["id"], row["title"], row["description"], row["path"] or "", *json.loads(row["evidence_json"])))
            matches = query_tokens.intersection(normalize_tokens([text]))
            if matches:
                scores[row["id"]] = len(matches) * 10
                evidence[row["id"]] = [f"text:{token}" for token in sorted(matches)]

        for profile in profiles:
            profile_matches = query_tokens.intersection(normalize_tokens(json.loads(profile["terms_json"])))
            if not profile_matches:
                continue
            for artifact_id in json.loads(profile["expected_artifacts_json"]):
                scores[artifact_id] = scores.get(artifact_id, 0) + len(profile_matches) * 4
                evidence.setdefault(artifact_id, []).append(f"task_profile:{profile['id']}")

        frontier = set(scores)
        visited = set(frontier)
        for hop, bonus in ((1, 3), (2, 1)):
            next_frontier: set[str] = set()
            for relation in relations:
                source_in_frontier = relation["source_id"] in frontier
                target_in_frontier = relation["target_id"] in frontier
                if source_in_frontier == target_in_frontier:
                    continue
                neighbor = relation["target_id"] if source_in_frontier else relation["source_id"]
                if neighbor not in visited:
                    scores[neighbor] = scores.get(neighbor, 0) + bonus
                    evidence.setdefault(neighbor, []).append(f"relation:{hop}:{relation['id']}")
                    next_frontier.add(neighbor)
            visited.update(next_frontier)
            frontier = next_frontier

        artifacts = {row["id"]: _artifact_from_row(row) for row in rows}
        return [
            SearchCandidate(artifacts[artifact_id], tuple(evidence[artifact_id] + [f"score:{scores[artifact_id]}"]))
            for artifact_id in sorted(scores, key=lambda item: (-scores[item], item))
            if artifact_id in artifacts
        ]


def _artifact_from_row(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"], artifact_type=row["artifact_type"], title=row["title"],
        description=row["description"], path=row["path"], evidence=json.loads(row["evidence_json"]),
        confidence=row["confidence"],
    )
