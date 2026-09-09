# Task 3 Implementation Report — CLI ingestion wiring

## Outcome

Implemented `sekr ingest neo4j --source PATH` with optional connection flags
and `--dry-run`.

Dry-run builds the validated projection and emits the deterministic projection
summary without resolving connection environment variables or invoking the
Neo4j adapter. Live ingestion resolves each connection value from its CLI flag
or corresponding `SEKR_NEO4J_*` environment variable, rejects incomplete
configuration as `INVALID_INPUT`, and serializes the adapter's `IngestSummary`.

## Changed files

- `src/sekr/cli.py`
  - Registers the `ingest neo4j` parser and options.
  - Builds a Task 1 projection for dry and live modes.
  - Implements dry-run and live JSON output contracts.
  - Resolves live-only connection values and calls the Task 2 adapter.
- `tests/test_cli.py`
  - Adds subprocess coverage for fixture dry-run output, missing live
    credentials, environment fallback through a monkeypatched adapter, and
    password non-disclosure.

## Commits

- `2253e8a Add Neo4j ingestion CLI command`

## Verification

Exact commands and observed outputs:

```text
pytest -q tests/test_cli.py -k ingest
4 passed, 12 deselected in 1.76s

pytest -q
147 passed in 32.70s
```

`git diff --check` completed with no whitespace errors.

## Self-review

- Confirmed only the task-owned CLI and test files were included in the
  implementation commit.
- Confirmed dry-run returns the required fixture payload: dataset version
  `0.1.0`, 13 nodes, 25 relationships, and `validated: true`.
- Confirmed environment lookup is below the dry-run return path, so dry-run
  does not read live credentials.
- Confirmed the Neo4j adapter defers driver import to `write_projection`; the
  CLI's dry-run branch never calls it.
- Confirmed validation errors use the existing structured JSON path with
  `INVALID_INPUT`, and tests verify passwords are absent from output streams.
- Confirmed live output uses only the required summary fields.

## Concerns

None. Existing uncommitted bytecode and Task 1/2 handoff artifacts were left
untouched.
