import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from sekr.db import init_db, load_dataset


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


@pytest.fixture
def runner():
    def run(*args):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path("src").resolve())
        return subprocess.run(
            [sys.executable, "-m", "sekr.cli", *args],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )

    return run


def remove_required_provenance(db_path):
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE artifacts SET evidence_json = ? WHERE id = ?",
            (json.dumps([]), "symbol.coder_value_service"),
        )


def test_context_compile_emits_json_and_zero_exit(seeded_db, runner):
    result = runner("context", "compile", "--db", str(seeded_db),
                    "--task", "activate coder values", "--budget", "5")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["task"] == "activate coder values"
    assert "items" in payload


def test_invalid_dataset_returns_structured_error(seeded_db, runner):
    remove_required_provenance(seeded_db)
    result = runner("dataset", "validate", "--db", str(seeded_db))
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"]["code"] == "DATASET_INVALID"


def test_dataset_load_initializes_and_replaces_database(tmp_path, runner):
    db_path = tmp_path / "knowledge.sqlite"
    result = runner("dataset", "load", "--db", str(db_path), "--source", "data/coder_activation.json")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["loaded"] is True
    assert payload["counts"] == {"artifacts": 9}
    assert payload["db"] == str(db_path)
    assert payload["source"] == "data/coder_activation.json"


def test_dataset_load_rejects_invalid_source_without_destroying_existing_database(seeded_db, tmp_path, runner):
    invalid_source = tmp_path / "broken.json"
    invalid_source.write_text("{", encoding="utf-8")

    result = runner("dataset", "load", "--db", str(seeded_db), "--source", str(invalid_source))

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_DATASET"
    assert json.loads(runner("dataset", "validate", "--db", str(seeded_db)).stdout)["valid"] is True


def test_compile_rejects_non_positive_budget_with_stdout_json(seeded_db, runner):
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate", "--budget", "0")

    assert result.returncode != 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_BUDGET"


def test_compile_requires_exactly_one_task_source(seeded_db, tmp_path, runner):
    task_file = tmp_path / "task.txt"
    task_file.write_text("activate coder values", encoding="utf-8")
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate", "--task-file", str(task_file), "--budget", "5")

    assert result.returncode != 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_INPUT"


def test_evaluate_accepts_data_and_oracle_paths_without_echoing_oracle(seeded_db, tmp_path, runner):
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text('{"secret": "do-not-echo"}', encoding="utf-8")
    result = runner("context", "evaluate", "--db", str(seeded_db), "--case", "coder-activation", "--data-dir", "data", "--oracle-path", str(oracle_path))

    assert result.returncode != 0
    assert result.stderr == ""
    assert "do-not-echo" not in result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "EVALUATION_UNAVAILABLE"


def test_evaluate_with_real_oracle_emits_metrics_only(seeded_db, runner):
    result = runner(
        "context",
        "evaluate",
        "--db",
        str(seeded_db),
        "--case",
        "coder-activation",
        "--oracle-path",
        "data/oracle/coder_activation.json",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"baseline", "case", "compiler", "reproducible", "warnings"}
    assert payload["case"] == "coder-activation"
    assert "expected_artifact_ids" not in result.stdout
    assert "critical_artifact_ids" not in result.stdout
    assert "feature.tenant_coder_activation" not in result.stdout


@pytest.mark.parametrize(("mutation", "issue"), [
    ("DELETE FROM dataset_metadata", "MISSING_METADATA"),
    ("UPDATE dataset_metadata SET generated_at = ' '", "INVALID_METADATA"),
    ("UPDATE facts SET evidence_json = '[null]'", "INVALID_EVIDENCE"),
    ("UPDATE task_profiles SET expected_artifacts_json = '[{}]'", "INVALID_TASK_PROFILE"),
])
def test_compile_cli_reports_malformed_dataset_as_json(seeded_db, runner, mutation, issue):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(mutation)
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate coder values", "--budget", "2")
    assert result.returncode == 1
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "DATASET_INVALID"
    assert error["details"]["issues"][0]["code"] == issue
