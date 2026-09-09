# Task 2 implementation report: Neo4j persistence adapter

## Changed files

- `src/sekr/neo4j.py`: added the lazy Neo4j driver boundary, fixed-label node and relationship MERGEs, atomic transaction handling, sanitized structured errors, and deterministic `IngestSummary` counts.
- `pyproject.toml`: added the optional `neo4j = ["neo4j>=5,<7"]` extra.
- `tests/test_neo4j.py`: added recording-driver coverage for query structure, 13 node / 25 relationship persistence, transaction commit, resource cleanup, fixed labels/types, parameterized properties, password exclusion, and connection-error mapping.
- `.superpowers/sdd/2026-09-09-sekr-p2-ingestion-neo4j/task-2-report.md`: this report.

## Commit

- `Implement Neo4j projection persistence adapter` (created for Task 2).

## Tests and outputs

- `pytest -q tests/test_neo4j.py` — `2 passed in 0.08s`.
- `pytest -q` — `139 passed in 26.77s`.
- `git diff --check` — passed; no whitespace errors.

## Self-review

- The Neo4j dependency is imported only in `write_projection`, so package import and dry-run paths do not require it.
- Driver creation receives credentials only through `auth=(user, password)`; query text is built solely from the closed fixed-label mapping, never dataset values or credentials.
- Dataset plus every projected node is written in one session and one transaction. Relationships use fixed `RELATES_TO`, merge by stable relationship ID, and retain their source vocabulary in `relation_type` along with every supplied property.
- All write-path exceptions trigger rollback where a transaction exists. Driver and session are closed in `finally`; structured error details contain only exception type names.
- No CLI, projection, compiler, or SQLite-schema files were modified.

## Concerns

- Unit coverage uses a recording fake by design; it does not exercise a live Neo4j server. A live integration test remains deferred to Task 4 per the brief.
