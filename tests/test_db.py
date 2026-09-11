from pathlib import Path
import json
import sqlite3

import pytest

from sekr.db import (
    KnowledgeRepository,
    init_db,
    load_dataset,
    normalize_tokens,
    validate_dataset,
)
from sekr.errors import StructuredError


def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def curated_dataset():
    return json.loads(Path("data/coder_activation.json").read_text(encoding="utf-8"))


def write_dataset(tmp_path, dataset):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    return dataset_path


def test_load_and_validate_curated_dataset(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    result = validate_dataset(db_path)
    assert result.valid is True
    assert result.artifact_count >= 8


def test_load_and_validate_preserves_provenance_on_all_stored_record_types(tmp_path):
    dataset = curated_dataset()
    provenance = {
        "source": "ADR 004",
        "evidence": ["docs/adr.md:1-2"],
        "source_version": "0.1",
        "content_hash": "sha256:" + "a" * 64,
        "observed_at": "2026-09-11T00:00:00Z",
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-09-30T00:00:00Z",
    }
    dataset["artifacts"][0].update(provenance)
    dataset["facts"][0].update(provenance)
    dataset["relations"][0].update(provenance)
    db_path = tmp_path / "knowledge.sqlite"

    load_dataset(db_path, write_dataset(tmp_path, dataset))

    assert validate_dataset(db_path).valid is True
    with sqlite3.connect(db_path) as connection:
        for table, identifier in (
            ("artifacts", dataset["artifacts"][0]["id"]),
            ("facts", dataset["facts"][0]["id"]),
            ("relations", dataset["relations"][0]["id"]),
        ):
            row = connection.execute(
                f"SELECT source, source_version, content_hash, observed_at, valid_from, valid_until FROM {table} WHERE id = ?",
                (identifier,),
            ).fetchone()
            assert row == tuple(provenance[field] if field != "evidence" else None for field in ("source", "source_version", "content_hash", "observed_at", "valid_from", "valid_until"))


def test_search_returns_service_query_and_test_candidates(tmp_path):
    db_path = seeded_db(tmp_path)
    candidates = KnowledgeRepository(db_path).search_candidates(
        ["coder", "activate", "active", "values"]
    )
    ids = {candidate.artifact.id for candidate in candidates}
    assert "symbol.coder_value_service" in ids
    assert "test.active_values_exclude_inactive" in ids


def test_search_retrieval_preserves_artifact_provenance(tmp_path):
    dataset = curated_dataset()
    provenance = {
        "source": "ADR 004", "evidence": ["docs/adr.md:1-2"],
        "source_version": "0.1", "content_hash": "sha256:" + "a" * 64,
        "observed_at": "2026-09-11T00:00:00Z",
        "valid_from": "2026-09-01T00:00:00Z",
        "valid_until": "2026-09-30T00:00:00Z",
    }
    dataset["artifacts"][0].update(provenance)
    db_path = tmp_path / "knowledge.sqlite"
    load_dataset(db_path, write_dataset(tmp_path, dataset))

    candidate = next(candidate for candidate in KnowledgeRepository(db_path).search_candidates(["coder"])
                     if candidate.artifact.id == dataset["artifacts"][0]["id"])

    assert candidate.artifact.id == dataset["artifacts"][0]["id"]
    assert {field: getattr(candidate.artifact, field) for field in provenance if field != "evidence"} == {
        field: provenance[field] for field in provenance if field != "evidence"
    }
    assert candidate.artifact.evidence == provenance["evidence"]


def test_loader_links_curated_facts_to_their_related_artifact(tmp_path):
    db_path = seeded_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        artifact_id = connection.execute(
            "SELECT artifact_id FROM facts WHERE id = ?",
            ("fact.active_query_filters_state",),
        ).fetchone()[0]

    assert artifact_id == "symbol.coder_value_service"


def test_loader_reports_malformed_dataset_as_structured_error(tmp_path):
    dataset_path = tmp_path / "broken.json"
    dataset_path.write_text("{", encoding="utf-8")

    with pytest.raises(StructuredError) as error:
        load_dataset(tmp_path / "knowledge.sqlite", dataset_path)

    assert error.value.code == "INVALID_DATASET"


def test_loader_reports_malformed_dataset_record_as_structured_error(tmp_path):
    dataset = curated_dataset()
    dataset["artifacts"] = ["not-an-artifact-record"]

    with pytest.raises(StructuredError) as error:
        load_dataset(tmp_path / "knowledge.sqlite", write_dataset(tmp_path, dataset))

    assert error.value.code == "INVALID_DATASET"


def test_loader_rejects_missing_raw_provenance(tmp_path):
    dataset = curated_dataset()
    dataset["artifacts"][0]["evidence"] = []
    dataset["artifacts"][0]["confidence"] = "VERIFIED"

    with pytest.raises(StructuredError) as error:
        load_dataset(tmp_path / "knowledge.sqlite", write_dataset(tmp_path, dataset))

    assert error.value.code == "MISSING_PROVENANCE"


@pytest.mark.parametrize(
    ("collection", "field"),
    [
        ("relations", "source_id"),
        ("facts", "artifact_id"),
        ("task_profiles", "expected_artifacts"),
    ],
)
def test_loader_reports_invalid_references_as_structured_errors(tmp_path, collection, field):
    dataset = curated_dataset()
    dataset[collection][0][field] = ["artifact.missing"] if field == "expected_artifacts" else "artifact.missing"

    with pytest.raises(StructuredError) as error:
        load_dataset(tmp_path / "knowledge.sqlite", write_dataset(tmp_path, dataset))

    assert error.value.code == "INVALID_REFERENCE"


def test_validate_dataset_reports_invalid_task_profile_references(tmp_path):
    db_path = seeded_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE task_profiles SET expected_artifacts_json = ? WHERE id = ?",
            (json.dumps(["artifact.missing"]), "profile.coder_activation"),
        )

    result = validate_dataset(db_path)

    assert result.valid is False
    assert [error.code for error in result.errors] == ["INVALID_REFERENCE"]


def test_normalize_tokens_is_ordered_lowercase_and_deduplicated():
    assert normalize_tokens(["CoderValueService", "ACTIVE-values", "coder"]) == (
        "codervalueservice",
        "active",
        "values",
        "coder",
    )


def test_search_includes_two_hop_candidates_without_backtracking_to_seeds(tmp_path):
    candidates = KnowledgeRepository(seeded_db(tmp_path)).search_candidates(["preserve", "history"])
    by_id = {candidate.artifact.id: candidate for candidate in candidates}

    assert "endpoint.coder_values" in by_id
    assert "relation:2:relation.feature_endpoint" in by_id["endpoint.coder_values"].score_evidence
    assert not any(
        evidence.startswith("relation:")
        for evidence in by_id["document.adr_coder_activation"].score_evidence
    )


def test_search_is_deterministic_and_excludes_unrelated_billing_control(tmp_path):
    repository = KnowledgeRepository(seeded_db(tmp_path))
    first = repository.search_candidates(["preserve", "history"])
    second = repository.search_candidates(["preserve", "history"])

    assert first == second
    assert "component.billing_invoice_export" not in {candidate.artifact.id for candidate in first}


@pytest.mark.parametrize("field", ["version", "source_commit", "generated_at"])
@pytest.mark.parametrize("value", ["", "  ", None, 42])
def test_loader_rejects_blank_or_non_text_metadata(tmp_path, field, value):
    dataset = curated_dataset()
    dataset["metadata"][field] = value
    with pytest.raises(StructuredError) as error:
        load_dataset(tmp_path / "knowledge.sqlite", write_dataset(tmp_path, dataset))
    assert error.value.code == "INVALID_METADATA"


@pytest.mark.parametrize("table", ["artifacts", "relations", "facts"])
@pytest.mark.parametrize("evidence", [[""], ["  "], [None], [42], ["source:1", None], "source:1", None, {}])
def test_loader_and_validator_reject_malformed_evidence(tmp_path, table, evidence):
    db_path = seeded_db(tmp_path)
    dataset = curated_dataset()
    dataset[table][0]["evidence"] = evidence
    with pytest.raises(StructuredError) as error:
        load_dataset(db_path, write_dataset(tmp_path, dataset))
    assert error.value.code == "INVALID_EVIDENCE"
    assert validate_dataset(db_path).valid  # Rejected loads preserve the dataset.
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"UPDATE {table} SET evidence_json = ?", (json.dumps(evidence),))
    result = validate_dataset(db_path)
    assert not result.valid
    assert result.errors[0].code == "INVALID_EVIDENCE"


@pytest.mark.parametrize("references", [[{}], [[]], [None], [42], [""], ["  "], "symbol.coder_value_service", None, {}])
def test_loader_and_validator_reject_malformed_profile_references(tmp_path, references):
    db_path = seeded_db(tmp_path)
    dataset = curated_dataset()
    dataset["task_profiles"][0]["expected_artifacts"] = references
    with pytest.raises(StructuredError) as error:
        load_dataset(db_path, write_dataset(tmp_path, dataset))
    assert error.value.code == "INVALID_TASK_PROFILE"
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE task_profiles SET expected_artifacts_json = ?", (json.dumps(references),))
    result = validate_dataset(db_path)
    assert not result.valid
    assert result.errors[0].code == "INVALID_TASK_PROFILE"


@pytest.mark.parametrize("field", ["version", "source_commit", "generated_at"])
def test_validator_reports_blank_required_metadata(tmp_path, field):
    db_path = seeded_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"UPDATE dataset_metadata SET {field} = '  '")
    assert validate_dataset(db_path).errors[0].code == "INVALID_METADATA"


@pytest.mark.parametrize(("table", "column"), [("artifacts", "evidence_json"), ("relations", "evidence_json"), ("facts", "evidence_json"), ("task_profiles", "terms_json"), ("task_profiles", "expected_artifact_types_json"), ("task_profiles", "expected_artifacts_json")])
def test_validator_reports_invalid_json_rows(tmp_path, table, column):
    db_path = seeded_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(f"UPDATE {table} SET {column} = '{{'")
    assert not validate_dataset(db_path).valid
