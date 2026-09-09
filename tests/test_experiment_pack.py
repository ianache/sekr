import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest


ROOT = Path(__file__).parents[1]
PACK = ROOT / "experiment-pack" / "v0.1"
DATASET = ROOT / "data" / "coder_activation.json"
ORACLE = ROOT / "data" / "oracle" / "coder_activation.json"
RUNNER = PACK / "run-experiment.ps1"
REPORT = PACK / "reports" / "EXPERIMENT_REPORT.md"
PROBE = ROOT.parent.parent / "build-standalone-probe-20260908" / "dist" / "sekr.exe"
RUNTIME_ARTIFACT_TYPES = {
    "feature",
    "endpoint",
    "symbol",
    "table",
    "test",
    "document",
    "repository",
}


def pack_files():
    return {path.name for path in PACK.iterdir()}


def test_pack_declares_p0_p1_contract():
    assert {"README.md", "ontology.md", "hypotheses.md", "expected-results.json"} <= pack_files()

    expected = json.loads((PACK / "expected-results.json").read_text(encoding="utf-8"))
    assert expected["case"] == "coder-activation"
    assert expected["budget"] == 6
    assert expected["acceptance"]["compilerCriticalRecall"] == 1.0


def test_final_report_preserves_the_approved_experiment_contract_without_oracle_disclosure():
    """Catches a final report that omits an approval result or leaks oracle data."""
    report = REPORT.read_text(encoding="utf-8")
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))

    assert "coder-activation" in report
    for section in (
        "## Inputs",
        "## Commands",
        "## Baseline metrics",
        "## Compiler metrics",
        "## Reproducibility",
        "## Acceptance results",
        "## Decision",
    ):
        assert section in report
    assert report.rstrip().endswith("GO")
    assert "FAIL:" not in report
    for metric in (
        "- precisionAtK: 0.8333333333333334",
        "- criticalRecall: 0.75",
        "- falsePositiveRate: 0.5",
        "- precisionAtK: 1.0",
        "- criticalRecall: 1.0",
        "- falsePositiveRate: 0.0",
        "- Deterministic repeated compiler output: True",
    ):
        assert metric in report
    acceptance_results = {
        "- PASS: Compiler precisionAtK is at least baseline",
        "- PASS: Compiler criticalRecall equals expected threshold",
        "- PASS: Compiler falsePositiveRate is at most baseline",
        "- PASS: Compiler result is reproducible",
        "- PASS: Compiler context is within budget",
        "- PASS: Truncation reports omittedCount and budget_truncated",
        "- PASS: Selected artifacts and facts retain valid evidence/confidence provenance",
        "- PASS: Evaluation output does not expose oracle IDs",
        "- PASS: Compiler fixture metrics match expected results",
        "- PASS: Baseline fixture metrics match expected results",
    }
    assert {line for line in report.splitlines() if line.startswith("- PASS:")} == acceptance_results
    assert "expected_artifact_ids" not in report
    assert "critical_artifact_ids" not in report
    assert all(artifact_id not in report for artifact_id in oracle["expected_artifact_ids"])
    assert all(artifact_id not in report for artifact_id in oracle["critical_artifact_ids"])


def test_oracle_ids_exist_in_fixture_and_critical_ids_are_expected():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))

    fixture_ids = {artifact["id"] for artifact in fixture["artifacts"]}
    expected_ids = set(oracle["expected_artifact_ids"])
    critical_ids = set(oracle["critical_artifact_ids"])

    assert expected_ids <= fixture_ids
    assert critical_ids <= expected_ids


def test_fixture_contains_required_p1_runtime_artifact_types():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))

    artifacts = {artifact["id"]: artifact for artifact in fixture["artifacts"]}
    artifact_types = {artifact["artifact_type"] for artifact in artifacts.values()}

    assert RUNTIME_ARTIFACT_TYPES <= artifact_types
    assert artifacts["document.adr_coder_activation"]["artifact_type"] == "document"
    assert artifacts["component.billing_invoice_export"]["artifact_type"] == "component"


def test_verified_and_approved_fixture_artifacts_and_relations_have_evidence():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))

    for collection in (fixture["artifacts"], fixture["relations"]):
        for record in collection:
            if record["confidence"] in {"VERIFIED", "APPROVED"}:
                assert record["evidence"], record["id"]


def test_ontology_declares_every_fixture_relationship_type():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    ontology = (PACK / "ontology.md").read_text(encoding="utf-8")

    relation_types = {relation["relation_type"].upper() for relation in fixture["relations"]}

    assert all(f"| `{relation_type}` |" in ontology for relation_type in relation_types)


def test_runner_executes_fixture_and_writes_experiment_outputs(tmp_path):
    """Catches a missing runner or a runner that does not produce its pack contract."""
    assert RUNNER.is_file()

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("No PowerShell executable is available; cannot run the runner smoke test")
    if not PROBE.is_file():
        pytest.skip("standalone probe executable is unavailable; cannot run the runner smoke test")

    output_dir = tmp_path / "experiment-output"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-File",
            str(RUNNER),
            "-Exe",
            str(PROBE),
            "-OutputDir",
            str(output_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert {
        "dataset-load.json",
        "dataset-validate.json",
        "context-compile.json",
        "evaluation.json",
        "environment.json",
        "EXPERIMENT_REPORT.md",
    } <= {path.name for path in output_dir.iterdir()}


def run_fixture_compile(tmp_path):
    database = tmp_path / "knowledge.sqlite"
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    load = subprocess.run(
        [sys.executable, "-m", "sekr.cli", "dataset", "load", "--db", str(database), "--source", str(DATASET)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )
    assert load.returncode == 0, load.stderr
    return database, environment


def test_compile_output_explicitly_reports_budget_truncation(tmp_path):
    """Catches removal of omittedCount or budget_truncated from the pack's concrete check."""
    database, environment = run_fixture_compile(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "sekr.cli", "context", "compile", "--db", str(database), "--task", "activate coder values", "--budget", "6"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["omittedCount"] > 0
    assert "budget_truncated" in payload["warnings"]


def test_compile_output_marks_evidence_free_selected_records_without_false_verification(tmp_path):
    """Catches selected artifacts or facts that retain VERIFIED confidence without evidence."""
    database, environment = run_fixture_compile(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE artifacts SET evidence_json = '[]', confidence = 'UNKNOWN' WHERE id = 'endpoint.coder_values'"
        )
        connection.execute(
            "UPDATE facts SET evidence_json = '[]', confidence = 'UNKNOWN' WHERE id = 'fact.active_query_filters_state'"
        )

    result = subprocess.run(
        [sys.executable, "-m", "sekr.cli", "context", "compile", "--db", str(database), "--task", "activate coder values", "--budget", "8"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    endpoint = next(item for item in payload["items"] if item["id"] == "endpoint.coder_values")
    fact = next(fact for item in payload["items"] for fact in item["facts"] if fact["id"] == "fact.active_query_filters_state")
    assert "missing_evidence" in payload["warnings"]
    assert endpoint["evidence"] == []
    assert endpoint["confidence"] not in {"VERIFIED", "APPROVED"}
    assert fact["evidence"] == []
    assert fact["confidence"] not in {"VERIFIED", "APPROVED"}


def test_evaluator_meets_expected_results_acceptance(tmp_path):
    database, environment = run_fixture_compile(tmp_path)
    expected = json.loads((PACK / "expected-results.json").read_text(encoding="utf-8"))

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "sekr.cli",
            "context",
            "evaluate",
            "--db",
            str(database),
            "--case",
            expected["case"],
            "--budget",
            str(expected["budget"]),
            "--oracle-path",
            str(ORACLE),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    evaluation = json.loads(result.stdout)
    compiler = evaluation["compiler"]
    baseline = evaluation["baseline"]
    acceptance = expected["acceptance"]

    assert compiler["criticalRecall"] == acceptance["compilerCriticalRecall"]
    assert compiler["precisionAtK"] >= baseline["precisionAtK"]
    assert compiler["falsePositiveRate"] <= baseline["falsePositiveRate"]
    assert evaluation["reproducible"] is acceptance["reproducible"]
    assert compiler["contextSize"] <= acceptance["maxSelectedItems"]
    assert "expected_artifact_ids" not in result.stdout
    assert "critical_artifact_ids" not in result.stdout
    oracle_ids = set(json.loads(ORACLE.read_text(encoding="utf-8"))["expected_artifact_ids"])
    oracle_ids.update(json.loads(ORACLE.read_text(encoding="utf-8"))["critical_artifact_ids"])
    assert all(oracle_id not in result.stdout for oracle_id in oracle_ids)
