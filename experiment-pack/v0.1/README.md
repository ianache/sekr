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

The future runner will write captured CLI JSON and a human-readable report to a
caller-provided output directory: `dataset-load.json`,
`dataset-validate.json`, `evaluation.json`, `environment.json`, and
`EXPERIMENT_REPORT.md`. A fresh SQLite database is created inside that output
directory for each run.

## Future runner command

Task 2 will introduce the reproducible Windows runner. Its direct invocation is:

```powershell
pwsh -NoProfile -File .\experiment-pack\v0.1\run-experiment.ps1 `
  -Exe .\build-standalone-probe-20260908\dist\sekr.exe `
  -OutputDir .\experiment-pack\v0.1\reports\latest
```

The runner will load and validate the fixture, evaluate the `coder-activation`
case at budget `K = 6`, compare metrics with the canonical expectations, check
reproducibility, and produce a GO decision only when acceptance passes.

## Scope

Neo4j, live ingestion, MCP integration, Knowledge Delta, executable
Knowledge-as-Tests rules, and agent/harness treatment runs are outside this
increment.
