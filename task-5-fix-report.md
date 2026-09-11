# Task 5 fix report

Addressed the integrated-review findings for P7.1 provenance/freshness:

- Canonical snapshots omit legacy projection-generated nullable provenance,
  while explicitly supplied null provenance remains rejected.
- Freshness validates snapshot provenance before evaluation and returns
  structured `INVALID_PROVENANCE`/`INVALID_EVIDENCE` errors.
- Scalar evidence is rejected consistently by shared validation and freshness.
- SQLite artifact retrieval preserves provenance fields through `Artifact`.
- Freshness output refuses the input path, the configured approved baseline,
  and the default `data/knowledge-baseline.json` path.
- GitLab freshness reporting is explicitly `allow_failure: true`; the
  blocking `knowledge-check` policy remains authoritative. README documents
  this distinction.
- Updated compiler integration fixtures for the expanded provenance schema
  and serialized nullable provenance fields.

Focused verification:

- `python -m pytest -q tests/test_freshness.py tests/test_knowledge_check.py tests/test_ingest.py tests/test_db.py tests/test_gitlab_ci.py` — 140 passed.
- `python -m pytest -q tests/test_cli.py -k knowledge_freshness` — 7 passed, 30 deselected.
- Full CLI/integrated runs were stopped at the user's request after the
  existing `delta` subprocess test stalled; no failure was attributed to the
  P7.1 freshness changes.
- `git diff --check` — passed.
