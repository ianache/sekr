# Task 2 Report — Reproducible Windows Runner

## Delivered

- Added `experiment-pack/v0.1/run-experiment.ps1` with `-Exe`, `-Dataset`,
  `-Oracle`, `-Expected`, and mandatory `-OutputDir` parameters.
- Resolved and validated all input files, created the SQLite database only as
  `knowledge.sqlite` below the resolved output directory, and captured each
  standalone executable command's JSON stdout without re-serializing it.
- Added `environment.json` with UTC timestamp, PowerShell version, OS, and
  SHA-256 hashes for the executable, dataset, and oracle.
- Added automatic acceptance checks for metric thresholds, canonical fixture
  metrics, reproducibility, budget/truncation evidence, and oracle-field
  non-disclosure. The runner writes `GO` only if every check passes and exits
  non-zero for failed acceptance.
- Updated the pack README with the required `pwsh -NoProfile` invocation.
- Added a real `pwsh` subprocess smoke test. It asserts the runner exists,
  runs the standalone probe when both dependencies are available, and asserts
  exit code zero plus all five output artifacts. It skips only with an explicit
  reason when `pwsh` or the standalone probe is unavailable.

## TDD evidence

1. Added the smoke test before creating the runner.
2. Ran `pytest -q tests/test_experiment_pack.py` before implementation:
   `1 failed, 3 passed`. The expected failure was `RUNNER.is_file()` because
   `run-experiment.ps1` did not yet exist.
3. Implemented the runner and documentation.
4. Found a PowerShell parser error during final verification: `$status:` in an
   interpolated report line was parsed as an invalid scoped variable. Corrected
   it to `${status}:` and re-ran the parser successfully.

## Verification

- PowerShell parser check using the installed Windows PowerShell parser: exit 0.
- Focused test suite: `pytest -q tests/test_experiment_pack.py` — `3 passed,
  1 skipped`.
- Full suite: `pytest -q` — `123 passed, 1 skipped`.

## Environment limitation

`pwsh` is not installed in this worktree environment, and the configured
standalone probe executable is also absent. The real subprocess smoke test is
therefore skipped with the explicit `pwsh is unavailable` reason. The runner
received syntax validation with the installed Windows PowerShell parser, but a
live standalone execution must be performed where both `pwsh` and
`build-standalone-probe-20260908/dist/sekr.exe` are available.

## Scope

No Neo4j, ingestion, Knowledge Delta, or Knowledge-as-Tests functionality was
implemented. The implementation changes are limited to the three Task 2 files;
this report is the separately required delivery record.

## Review Fixes — Explicit Truncation and Provenance

### Finding 1: truncation was inferred rather than explicitly reported

The prior runner compared evaluation `contextSize` with `candidateCount`. That
could pass when fewer results were selected without proving that the Compiler
reported either `omittedCount` or `budget_truncated`.

The runner now executes and preserves this additional standalone command:

```text
sekr.exe context compile --db <output db> --task "activate coder values" --budget 6
```

Its unchanged JSON stdout is written to `context-compile.json`. Acceptance now
requires both `omittedCount > 0` and `warnings` to include `budget_truncated`.
The generated experiment report lists the command, omitted count, warnings, and
selected-item count. The existing load, validate, and evaluate commands and
outputs remain unchanged.

### Finding 2: selected provenance was not checked

The runner now inspects the captured compile JSON. Every selected item and each
attached fact must expose a recognized confidence value and an evidence field.
When evidence is empty, the record must not be `VERIFIED` or `APPROVED`, and
the compile warnings must include `missing_evidence`. The fixed fixture also
requires at least one selected item, preventing an empty package from passing
the provenance check.

### Regression coverage

- `test_compile_output_explicitly_reports_budget_truncation` runs the real CLI
  against the fixture and requires `omittedCount > 0` plus
  `budget_truncated` for budget 6.
- `test_compile_output_marks_evidence_free_selected_records_without_false_verification`
  creates valid evidence-free `UNKNOWN` artifact and fact records in a
  temporary SQLite database, runs the real CLI, and requires
  `missing_evidence` while rejecting `VERIFIED` and `APPROVED` confidence.
- The `pwsh` smoke test now asserts `context-compile.json` alongside the
  previously required outputs. It remains explicitly skipped here because
  `pwsh` and the standalone probe executable are unavailable.

### Commands and observed output

```text
python -m sekr.cli dataset load --db %TEMP%\sekr-review.sqlite --source data\coder_activation.json
```

Output: exit 0; loaded 9 artifacts.

```text
python -m sekr.cli context compile --db %TEMP%\sekr-review.sqlite --task "activate coder values" --budget 6
```

Output: exit 0; `omittedCount: 2`, warnings include `budget_truncated`, six
selected items, and selected artifact/fact records contain evidence and
confidence fields.

```text
PowerShell AST ParseFile experiment-pack/v0.1/run-experiment.ps1
```

Output: exit 0; no parser errors.

```text
pytest -q tests/test_experiment_pack.py
```

Output: `5 passed, 1 skipped in 1.89s`.

```text
pytest -q
```

Output: `125 passed, 1 skipped in 23.29s`.
