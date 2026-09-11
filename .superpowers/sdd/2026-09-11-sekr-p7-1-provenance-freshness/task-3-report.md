# Task 3 report — Provenance validation and snapshot compatibility

## Status

DONE

Added validation to `check_knowledge` for optional provenance fields. Invalid
types, non-lowercase/non-64-character SHA-256 hashes, and timezone-naive or
malformed timestamps raise `INVALID_PROVENANCE` with stable `field` and
`record` details. Absent provenance remains valid, and the existing projection
evidence representation (string lists, including nullable structural evidence)
remains compatible.

## TDD evidence

- RED: new provenance tests failed because malformed fields were not rejected.
- GREEN: focused provenance and legacy-compatibility tests passed.

## Verification

- `pytest -q tests/test_knowledge_check.py tests/test_ingest.py` → `38 passed in 1.15s`
- `git diff --check` → exit 0

## Concerns

The worktree contains pre-existing generated `__pycache__` changes and SDD
ledger files; they were not modified or included in this commit. `evidence`
continues to accept the repository’s established list-of-strings projection
shape in addition to a string.
