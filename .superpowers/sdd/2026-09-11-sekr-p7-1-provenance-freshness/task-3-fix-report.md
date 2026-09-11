# Task 3 fix report — provenance validation and snapshot compatibility

## Status

DONE

## Fixed findings

- Optional provenance is presence-aware: omitted fields remain compatible, while explicit null and invalid present scalar values are rejected.
- Timestamps now require the strict UTC-compatible form `YYYY-MM-DDTHH:MM:SS[.fraction](Z|+00:00)` and are validated consistently by knowledge checks and freshness parsing.
- `source`, `evidence`, `source_version`, `content_hash`, `observed_at`, `valid_from`, and `valid_until` are carried through dataset validation, SQLite loading, ingest projection, model construction, and canonical snapshots for artifacts, facts, and relations.
- Existing legacy database rows and generated structural relationship evidence remain compatible; established malformed-evidence errors retain `INVALID_EVIDENCE`.

## Tests

Fresh focused verification:

```text
python -m pytest -q tests/test_knowledge_check.py tests/test_ingest.py --basetemp .pytest-tmp-task3-required-verification
55 passed in 1.74s
```

Focused propagation verification:

```text
python -m pytest -q tests/test_knowledge_check.py tests/test_ingest.py tests/test_db.py tests/test_models.py --basetemp .pytest-tmp-task3-final-verification
130 passed in 13.57s
```

`git diff --check f75e293..HEAD` exited 0. The full repository suite was intentionally not run.

## Commit lineage

- Provenance source and test changes: `d42aacf5c8b78c4def5690f6c7e864b7881cdc2e fix: close provenance validation review findings`
- This report correction is committed separately after fresh verification.
