# Task 3 fix report — provenance validation and snapshot compatibility

## Status

DONE_WITH_CONCERNS

## Fixed findings

- Optional provenance is presence-aware: omitted fields remain compatible, while explicit null and invalid present scalar values are rejected.
- Timestamps now require the strict UTC-compatible form `YYYY-MM-DDTHH:MM:SS[.fraction](Z|+00:00)` and are validated consistently by knowledge checks and freshness parsing.
- `source`, `evidence`, `source_version`, `content_hash`, `observed_at`, `valid_from`, and `valid_until` are carried through dataset validation, SQLite loading, ingest projection, model construction, and canonical snapshots for artifacts, facts, and relations.
- Existing legacy database rows and generated structural relationship evidence remain compatible; established malformed-evidence errors retain `INVALID_EVIDENCE`.

## Tests

Focused provenance suite:

```text
pytest -q tests/test_knowledge_check.py tests/test_ingest.py tests/test_db.py tests/test_models.py --basetemp .pytest-tmp-task3-fix-final
130 passed in 77.79s (0:01:17)
```

Required command:

```text
pytest -q tests/test_knowledge_check.py tests/test_ingest.py
55 passed in 9.38s
```

The full repository suite was not rerun in this interrupted iteration.

## Commit

Commit: `2fdd156 fix: close provenance validation review findings`
