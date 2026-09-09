import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
PACK = ROOT / "experiment-pack" / "v0.1"
DATASET = ROOT / "data" / "coder_activation.json"
ORACLE = ROOT / "data" / "oracle" / "coder_activation.json"
RUNNER = PACK / "run-experiment.ps1"
PROBE = ROOT / "build-standalone-probe-20260908" / "dist" / "sekr.exe"


def pack_files():
    return {path.name for path in PACK.iterdir()}


def test_pack_declares_p0_p1_contract():
    assert {"README.md", "ontology.md", "hypotheses.md", "expected-results.json"} <= pack_files()

    expected = json.loads((PACK / "expected-results.json").read_text(encoding="utf-8"))
    assert expected["case"] == "coder-activation"
    assert expected["budget"] == 6
    assert expected["acceptance"]["compilerCriticalRecall"] == 1.0


def test_oracle_ids_exist_in_fixture_and_critical_ids_are_expected():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    oracle = json.loads(ORACLE.read_text(encoding="utf-8"))

    fixture_ids = {artifact["id"] for artifact in fixture["artifacts"]}
    expected_ids = set(oracle["expected_artifact_ids"])
    critical_ids = set(oracle["critical_artifact_ids"])

    assert expected_ids <= fixture_ids
    assert critical_ids <= expected_ids


def test_ontology_declares_every_fixture_relationship_type():
    fixture = json.loads(DATASET.read_text(encoding="utf-8"))
    ontology = (PACK / "ontology.md").read_text(encoding="utf-8")

    relation_types = {relation["relation_type"].upper() for relation in fixture["relations"]}

    assert all(f"`{relation_type}`" in ontology for relation_type in relation_types)


def test_runner_executes_fixture_and_writes_experiment_outputs(tmp_path):
    """Catches a missing runner or a runner that does not produce its pack contract."""
    assert RUNNER.is_file()

    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is unavailable; cannot run the Windows runner smoke test")
    if not PROBE.is_file():
        pytest.skip("standalone probe executable is unavailable; cannot run the runner smoke test")

    output_dir = tmp_path / "experiment-output"
    result = subprocess.run(
        [
            pwsh,
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
        "evaluation.json",
        "environment.json",
        "EXPERIMENT_REPORT.md",
    } <= {path.name for path in output_dir.iterdir()}
