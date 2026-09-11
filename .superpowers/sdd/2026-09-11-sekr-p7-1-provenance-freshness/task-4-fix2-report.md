# Task 4 fix round 2 report

Removed the undeclared PyYAML dependency from `tests/test_gitlab_ci.py`.
The CI contract test now uses a small standard-library text parser that
validates the YAML mapping shape needed by the contract and retains assertions
for the global `python:3.12-slim` image and the absence of a job-level image
override on `knowledge-freshness`.

Verification:

- `python -m pytest -q tests/test_gitlab_ci.py tests/test_freshness.py tests/test_cli.py -k "freshness or gitlab"` — **15 passed, 30 deselected in 3.70s**.
- `git diff --check` — **passed** (exit 0).

Self-review:

- No production code, CI configuration, or documentation was changed.
- The test module no longer imports PyYAML, and the dependency remains absent
  from `pyproject.toml`.
