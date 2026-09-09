# SEKR P0 + P1 Experiment Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible `experiment-pack/v0.1` that formally closes P0 and P1 using the existing curated Tenant/Coder fixture and deterministic SQLite/CLI runtime.

**Architecture:** Keep the current Python/SQLite runtime unchanged except where a test exposes a missing contract. Add a pack-level contract, a PowerShell runner that treats the standalone CLI as the system under test, canonical expected metrics, and a generated Markdown report. Define `Change` and `KnowledgeRule` in documentation only; do not add their runtime behavior in this plan.

**Tech Stack:** Python 3.11+, existing `sekr` CLI, SQLite, PowerShell, JSON, Markdown, pytest, PyInstaller-built Windows executable.

**Spec:** `docs/superpowers/specs/2026-09-08-sekr-p0-p1-experiment-pack-design.md`

## Global Constraints

- Use the existing curated fixture `data/coder_activation.json` as the only P0 corpus.
- Keep the oracle at `data/oracle/coder_activation.json` separate from Compiler output.
- Do not implement Neo4j, live repository ingestion, MCP, Knowledge Delta, or executable Knowledge-as-Tests.
- P0 acceptance uses budget `K = 6`.
- Compiler `criticalRecall` must equal `1.0`; Compiler precision and false-positive rate must be no worse than baseline.
- Repeated Compiler output must be identical after canonical JSON serialization.
- Evidence-free `VERIFIED`/`APPROVED` records must never be reported as verified.
- Every task follows red-green-refactor and ends with a fresh verification command.

---

### Task 1: Create the P0/P1 pack contract and canonical expectations

**Files:**
- Create: `experiment-pack/v0.1/README.md`
- Create: `experiment-pack/v0.1/ontology.md`
- Create: `experiment-pack/v0.1/hypotheses.md`
- Create: `experiment-pack/v0.1/expected-results.json`
- Test: `tests/test_experiment_pack.py`

**Interfaces:**
- Consumes: `data/coder_activation.json`, `data/oracle/coder_activation.json`, and the approved design spec.
- Produces: stable pack documentation and a machine-readable expected-results contract consumed by the runner and tests.

- [ ] **Step 1: Write failing contract tests**

  Add tests that load the four pack files and assert:

  ```python
  def test_pack_declares_p0_p1_contract():
      assert {"README.md", "ontology.md", "hypotheses.md", "expected-results.json"} <= pack_files()
      expected = json.loads((PACK / "expected-results.json").read_text(encoding="utf-8"))
      assert expected["case"] == "coder-activation"
      assert expected["budget"] == 6
      assert expected["acceptance"]["compilerCriticalRecall"] == 1.0
  ```

  Add a second test that asserts every artifact ID in the oracle exists in the fixture and every critical ID is expected.

- [ ] **Step 2: Run the new tests and verify the intended failure**

  Run:

  ```powershell
  pytest -q tests/test_experiment_pack.py
  ```

  Expected: FAIL because `experiment-pack/v0.1` does not exist.

- [ ] **Step 3: Write the pack contract files**

  `expected-results.json` must contain this shape:

  ```json
  {
    "case": "coder-activation",
    "budget": 6,
    "acceptance": {
      "compilerPrecisionAtKAtLeastBaseline": true,
      "compilerCriticalRecall": 1.0,
      "compilerFalsePositiveRateAtMostBaseline": true,
      "reproducible": true,
      "maxSelectedItems": 6,
      "oracleNotExposed": true
    },
    "expectedFixture": {
      "compiler": {"precisionAtK": 1.0, "criticalRecall": 1.0, "falsePositiveRate": 0.0},
      "baseline": {"precisionAtK": 0.8333333333333334, "criticalRecall": 0.75, "falsePositiveRate": 0.5}
    }
  }
  ```

  `hypotheses.md` must state H1–H4, the controlled task, budget, oracle boundary and the six acceptance rules. `ontology.md` must list all P1 entities, including `Change` and `KnowledgeRule` as documentation-only types, all relationship names, confidence values and provenance requirements. `README.md` must explain the pack purpose, inputs, outputs and the exact runner command introduced in Task 2.

- [ ] **Step 4: Run the contract tests**

  Run:

  ```powershell
  pytest -q tests/test_experiment_pack.py
  ```

  Expected: PASS.

- [ ] **Step 5: Commit the contract**

  ```powershell
  git add experiment-pack/v0.1 tests/test_experiment_pack.py
  git commit -m "docs: add sekr p0 p1 experiment contract"
  ```

### Task 2: Add the reproducible Windows experiment runner

**Files:**
- Create: `experiment-pack/v0.1/run-experiment.ps1`
- Modify: `experiment-pack/v0.1/README.md`
- Modify: `tests/test_experiment_pack.py`

**Interfaces:**
- Consumes: standalone executable path, fixture path, oracle path, expected-results path.
- Produces: `dataset-load.json`, `dataset-validate.json`, `evaluation.json`, `environment.json`, and `EXPERIMENT_REPORT.md` under a caller-provided output directory.

- [ ] **Step 1: Add a failing runner smoke test**

  Extend the test module with a subprocess test that invokes PowerShell using the repository executable and a temporary output directory:

  ```python
  def test_runner_writes_reproducible_outputs(tmp_path):
      result = subprocess.run(
          ["pwsh", "-NoProfile", "-File", str(RUNNER),
           "-Exe", str(EXE), "-OutputDir", str(tmp_path / "run")],
          capture_output=True, text=True, check=False,
      )
      assert result.returncode == 0, result.stdout + result.stderr
      assert (tmp_path / "run" / "evaluation.json").exists()
      assert (tmp_path / "run" / "EXPERIMENT_REPORT.md").exists()
  ```

  Skip the test only when `pwsh` or the probe executable is unavailable, with an explicit skip reason; do not silently pass.

- [ ] **Step 2: Run the smoke test and verify it fails**

  ```powershell
  pytest -q tests/test_experiment_pack.py -k runner
  ```

  Expected: FAIL because `run-experiment.ps1` does not exist.

- [ ] **Step 3: Implement the runner**

  Define parameters:

  ```powershell
  param(
    [string]$Exe = (Join-Path $PSScriptRoot "..\..\build-standalone-probe-20260908\dist\sekr.exe"),
    [string]$Dataset = (Join-Path $PSScriptRoot "..\..\data\coder_activation.json"),
    [string]$Oracle = (Join-Path $PSScriptRoot "..\..\data\oracle\coder_activation.json"),
    [string]$Expected = (Join-Path $PSScriptRoot "expected-results.json"),
    [Parameter(Mandatory=$true)][string]$OutputDir
  )
  ```

  The script must:

  1. Resolve all paths and fail with a non-zero exit code if the executable, dataset, oracle or expected-results file is missing.
  2. Create only the specified output directory and a database inside it.
  3. Run `dataset load`, `dataset validate`, and `context evaluate --case coder-activation --budget 6 --oracle-path $Oracle` with captured stdout JSON.
  4. Write each JSON payload to its named output file without echoing oracle contents.
  5. Write `environment.json` with PowerShell version, OS, executable SHA-256, dataset SHA-256, oracle SHA-256 and UTC execution timestamp.
  6. Compare evaluation metrics with `expected-results.json` and exit `1` if any acceptance criterion fails.
  7. Generate `EXPERIMENT_REPORT.md` containing inputs, commands, baseline metrics, Compiler metrics, reproducibility, acceptance results and a final `GO` decision only when all acceptance checks pass.

- [ ] **Step 4: Run the runner smoke test**

  ```powershell
  pytest -q tests/test_experiment_pack.py -k runner
  ```

  Expected: PASS and both JSON output and Markdown report exist.

- [ ] **Step 5: Document direct execution**

  Add this exact command to the pack README:

  ```powershell
  pwsh -NoProfile -File .\experiment-pack\v0.1\run-experiment.ps1 `
    -Exe .\build-standalone-probe-20260908\dist\sekr.exe `
    -OutputDir .\experiment-pack\v0.1\reports\latest
  ```

- [ ] **Step 6: Commit the runner**

  ```powershell
  git add experiment-pack/v0.1/run-experiment.ps1 experiment-pack/v0.1/README.md tests/test_experiment_pack.py
  git commit -m "feat: add reproducible sekr experiment runner"
  ```

### Task 3: Validate P1 runtime mapping and acceptance behavior

**Files:**
- Modify: `tests/test_experiment_pack.py`
- Modify: `experiment-pack/v0.1/ontology.md` only if the tests expose a vocabulary mismatch
- Modify: `data/coder_activation.json` only if an explicit ontology/provenance defect is found

**Interfaces:**
- Consumes: loaded SQLite fixture, ontology catalog and oracle.
- Produces: automated proof that the runtime model satisfies the P1 contract without adding `Change` or `KnowledgeRule` runtime types.

- [ ] **Step 1: Add failing P1 mapping tests**

  Assert the fixture contains the required runtime artifact types, relation types, confidence values and evidence:

  ```python
  def test_fixture_covers_p1_runtime_vocabulary():
      dataset = json.loads(DATASET.read_text(encoding="utf-8"))
      artifact_types = {item["artifact_type"] for item in dataset["artifacts"]}
      assert {"feature", "endpoint", "symbol", "table", "test", "document", "repository"} <= artifact_types
      assert all(item["evidence"] for item in dataset["artifacts"] if item["confidence"] in {"VERIFIED", "APPROVED"})
      assert all(item["evidence"] for item in dataset["relations"] if item["confidence"] in {"VERIFIED", "APPROVED"})
  ```

  Add an acceptance test that invokes the existing evaluator and checks all six P0 acceptance rules against the canonical expected-results file.

- [ ] **Step 2: Run the P1 tests and inspect any failure**

  ```powershell
  pytest -q tests/test_experiment_pack.py -k "p1 or acceptance"
  ```

  Expected: FAIL only if the current fixture or documented vocabulary is inconsistent; record the exact mismatch before changing data.

- [ ] **Step 3: Make the smallest data or documentation correction**

  Preserve the existing nine-artifact experiment and its oracle. Do not add speculative entities or relations. If no mismatch exists, leave runtime files unchanged and only keep the tests as the P1 proof.

- [ ] **Step 4: Run the full test suite**

  ```powershell
  pytest -q
  ```

  Expected: all existing tests plus the experiment-pack tests pass.

- [ ] **Step 5: Commit the P1 verification**

  ```powershell
  git add tests/test_experiment_pack.py experiment-pack/v0.1/ontology.md data/coder_activation.json
  git commit -m "test: verify sekr p1 ontology mapping"
  ```

### Task 4: Generate and review the final Experiment Pack report

**Files:**
- Create: `experiment-pack/v0.1/reports/EXPERIMENT_REPORT.md`
- Modify: `experiment-pack/v0.1/README.md`
- Test: `tests/test_experiment_pack.py`

**Interfaces:**
- Consumes: runner output from Task 2 and canonical expectations from Task 1.
- Produces: committed, human-readable P0/P1 result with evidence and decision.

- [ ] **Step 1: Run the runner against a clean output directory**

  ```powershell
  pwsh -NoProfile -File .\experiment-pack\v0.1\run-experiment.ps1 `
    -Exe .\build-standalone-probe-20260908\dist\sekr.exe `
    -OutputDir .\experiment-pack\v0.1\reports\latest
  ```

  Expected: exit code `0`, `evaluation.json` reports Compiler precision `1.0`, critical recall `1.0`, false-positive rate `0.0`, and the report ends with `GO` for the bounded P0/P1 experiment.

- [ ] **Step 2: Add report integrity assertions**

  Assert the committed report contains the case name, both metric sections, reproducibility, acceptance results and `GO`, but does not contain oracle field names or the complete oracle ID lists.

- [ ] **Step 3: Run final verification**

  ```powershell
  pytest -q
  pwsh -NoProfile -File .\experiment-pack\v0.1\run-experiment.ps1 -Exe .\build-standalone-probe-20260908\dist\sekr.exe -OutputDir .\experiment-pack\v0.1\reports\verification
  ```

  Expected: all tests pass and the runner exits `0`.

- [ ] **Step 4: Commit the completed pack**

  ```powershell
  git add experiment-pack/v0.1 tests/test_experiment_pack.py
  git commit -m "feat: complete sekr p0 p1 experiment pack"
  ```

## Plan self-review

- **Spec coverage:** P0 case, hypotheses, oracle, thresholds, protocol, P1 entity and relationship catalog, provenance, runtime mapping, pack outputs and verification are covered by Tasks 1–4.
- **Scope check:** the plan contains one bounded deliverable: a documentation-and-runner experiment pack over the existing SQLite/CLI runtime. Neo4j, ingestion, Delta and Knowledge-as-Tests remain explicit non-goals.
- **Open-item scan:** every implementation step names its files, inputs, command and expected result; no unspecified implementation step or vague validation instruction remains.
- **Type/contract check:** the runner consumes the existing CLI commands and writes the exact JSON files named in Task 2; expected-results keys match the acceptance checks named in Tasks 1, 3 and 4.
