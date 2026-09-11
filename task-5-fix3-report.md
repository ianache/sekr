# Task 5 fix3 report

Closed the five residual P7.1 findings in the approved provenance/freshness
worktree.

- Legacy approved baselines accept projection-generated `valid_from: null`
  while current/user-supplied explicit null provenance remains rejected.
  `knowledge-check` and `knowledge-freshness` now produce structured reports
  for the committed baseline.
- Freshness output safety resolves paths independently of the process cwd and
  rejects collisions with referenced `evidence`, `path`, or `source` files,
  the input, and approved baseline artifacts.
- `KnowledgeRepository` initializes/migrates pre-P7.1 SQLite schemas before
  normal reads, allowing compiler and DB retrieval to use legacy databases.
- Freshness honors `freshness: "stale"` after evidence verification.
- Freshness structurally requires relationship endpoints and rejects missing or
  non-string endpoint fields with `StructuredError` rather than leaking a
  `TypeError`.

Focused verification:

- `tests/test_freshness.py` targeted residual regressions: **6 passed**.
- `tests/test_cli.py` targeted baseline/output regressions: **3 passed**.
- `tests/test_knowledge_check.py` explicit-null/legacy/structure checks:
  **12 passed**.
- `tests/test_db.py` pre-P7.1 migration check: **1 passed**.

The full suite was not rerun because the user requested that long-running tests
be stopped. Pre-existing untracked files and bytecode changes were not staged.
