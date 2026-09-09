# SEKR Experiment Pack v0.1

This pack defines the bounded P0/P1 experiment for Tenant/Coder activation and
deactivation. It formalizes the retrieval task, evaluation boundary, canonical
metrics, and the minimum knowledge model over the existing deterministic
JSON/SQLite runtime.

## Controlled task

Activate and deactivate individual Tenant Coder values while ensuring that
active-value queries exclude inactive values and deactivation preserves
history. The pack uses controlled evidence paths from the curated fixture; it
does not perform live repository ingestion.

## Inputs

- `data/coder_activation.json` — curated Tenant/Coder artifacts, relations,
  facts, and task profile.
- `data/oracle/coder_activation.json` — evaluation-only expected and critical
  artifact IDs. The Compiler output must not expose these oracle fields.
- `expected-results.json` — budget, acceptance thresholds, and expected
  fixture metrics.

## Outputs

The runner writes captured CLI JSON and a human-readable report to a
caller-provided output directory: `dataset-load.json`,
`dataset-validate.json`, `context-compile.json`, `evaluation.json`, `environment.json`, and
`EXPERIMENT_REPORT.md`. A fresh SQLite database is created inside that output
directory for each run.

The committed final result for this pack is
[`reports/EXPERIMENT_REPORT.md`](reports/EXPERIMENT_REPORT.md). It records the
controlled case, command protocol, metrics, reproducibility evidence, and the
P0 decision without reproducing evaluation-only oracle contents.

## Run the experiment

Run the reproducible Windows runner from the repository root:

```powershell
pwsh -NoProfile -File .\experiment-pack\v0.1\run-experiment.ps1 `
  -Exe .\build-standalone-probe-20260908\dist\sekr.exe `
  -OutputDir .\experiment-pack\v0.1\reports\latest
```

The runner loads and validates the fixture, captures a `context compile` result
for `activate coder values` at budget `K = 6`, evaluates the
`coder-activation` case at the same budget, compares metrics with the canonical
expectations, checks explicit truncation and selected-item provenance, and
produces a GO decision only when acceptance passes.

Run it with PowerShell 7+ (`pwsh`), which supplies the .NET process argument
API used by the runner. The committed report can be inspected independently of
the per-run output directory.

## Scope

Neo4j, live ingestion, MCP integration, Knowledge Delta, executable
Knowledge-as-Tests rules, and agent/harness treatment runs are outside this
increment.
