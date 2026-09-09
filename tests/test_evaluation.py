from pathlib import Path
import json
import sqlite3

import pytest

from sekr.compiler import ContextCompiler, _text_baseline_ids, evaluate_case
from sekr.db import KnowledgeRepository, init_db, load_dataset
from sekr.errors import StructuredError


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


@pytest.fixture
def oracle_path():
    return Path("data/oracle/coder_activation.json")


def test_evaluation_compares_compiler_with_text_baseline(seeded_db, oracle_path):
    report = evaluate_case(seeded_db, oracle_path, case="coder-activation", budget=6)

    assert report.compiler.precision_at_k >= report.baseline.precision_at_k
    assert report.compiler.critical_recall >= 0.75
    assert report.compiler.context_size == 6


def test_repeated_compilation_is_reproducible(seeded_db):
    compiler = ContextCompiler(KnowledgeRepository(seeded_db))
    first = compiler.compile("activate coder values", budget=5).to_dict()
    second = compiler.compile("activate coder values", budget=5).to_dict()

    assert first == second


def test_evaluation_reports_zero_denominators_and_false_positive_ids(seeded_db, tmp_path):
    oracle = tmp_path / "empty.json"
    oracle.write_text(
        '{"expected_artifact_ids": [], "critical_artifact_ids": []}',
        encoding="utf-8",
    )

    report = evaluate_case(seeded_db, oracle, case="coder-activation", budget=2)

    assert report.compiler.precision_at_k == 0.0
    assert report.compiler.critical_recall == 0.0
    assert report.compiler.false_positive_rate == pytest.approx(2 / 9)
    assert report.compiler.false_positive_ids == (
        "feature.tenant_coder_activation",
        "test.active_values_exclude_inactive",
    )


def test_text_baseline_uses_literal_task_tokens_without_compiler_expansion(seeded_db):
    baseline_ids = _text_baseline_ids(seeded_db, "activate coder values", budget=6)

    assert baseline_ids == (
        "feature.tenant_coder_activation",
        "document.adr_coder_activation",
        "endpoint.coder_values",
        "repository.tenant_coder_repository",
        "symbol.coder_value_service",
        "table.tenant_coder_values",
    )


def test_false_positive_rate_uses_all_dataset_negatives(seeded_db, oracle_path):
    report = evaluate_case(seeded_db, oracle_path, case="coder-activation", budget=6)
    # Nine artifacts, seven oracle positives: FP=1, TN=1, not FP / six selected.
    assert report.baseline.false_positive_ids == ("repository.tenant_coder_repository",)
    assert report.baseline.false_positive_rate == 0.5
    assert report.baseline.candidate_count == 9
    assert report.baseline.true_negative_count == 1
    assert report.compiler.false_positive_rate == 0.0
    assert report.compiler.true_negative_count == 2


def test_evaluation_measures_serialized_utf8_context_bytes(seeded_db, oracle_path):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("UPDATE artifacts SET description = description || ' café' WHERE id = 'feature.tenant_coder_activation'")
    report = evaluate_case(seeded_db, oracle_path, case="coder-activation", budget=6)
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", 6)
    serialized = json.dumps(package.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert report.compiler.context_size_bytes == len(serialized.encode("utf-8"))
    assert report.compiler.context_size_bytes > len(serialized)
    fixture = json.loads(Path("data/coder_activation.json").read_text(encoding="utf-8"))
    records = {entry["id"]: dict(entry) for entry in fixture["artifacts"]}
    records["feature.tenant_coder_activation"]["description"] += " café"
    baseline = []
    for identifier in _text_baseline_ids(seeded_db, "activate coder values", 6):
        record = records[identifier]
        record["artifactType"] = record.pop("artifact_type")
        baseline.append(record)
    assert report.baseline.context_size_bytes == len(json.dumps(baseline, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert report.to_dict()["compiler"]["contextSizeBytes"] > 0


def test_false_positive_rate_with_no_negative_candidates(seeded_db, tmp_path):
    with sqlite3.connect(seeded_db) as connection:
        ids = [row[0] for row in connection.execute("SELECT id FROM artifacts")]
    oracle = tmp_path / "all-positive.json"
    oracle.write_text(json.dumps({"expected_artifact_ids": ids, "critical_artifact_ids": []}), encoding="utf-8")
    report = evaluate_case(seeded_db, oracle, case="coder-activation", budget=2)
    assert report.compiler.false_positive_rate == 0.0
    assert report.compiler.true_negative_count == 0


@pytest.mark.parametrize(("expected", "critical"), [(["missing.artifact"], []), ([], ["feature.tenant_coder_activation"])])
def test_evaluation_rejects_oracle_outside_candidate_universe(seeded_db, tmp_path, expected, critical):
    oracle = tmp_path / "invalid-universe.json"
    oracle.write_text(json.dumps({"expected_artifact_ids": expected, "critical_artifact_ids": critical}), encoding="utf-8")
    with pytest.raises(StructuredError) as error:
        evaluate_case(seeded_db, oracle, case="coder-activation", budget=2)
    assert error.value.code == "EVALUATION_UNAVAILABLE"
