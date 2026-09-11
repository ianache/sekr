# Task 4 report — GitLab freshness report job and documentation

Implemented the `knowledge-freshness` GitLab job after `knowledge-check` with
the fixed `SEKR_KNOWLEDGE_AS_OF` default, the required read-only CLI command,
and a one-week always-published JSON artifact. Added local and GitLab usage
documentation distinguishing freshness reporting from baseline approval, plus
YAML and documentation contract tests.

Verification:

- `python -m pytest -q tests/test_gitlab_ci.py tests/test_freshness.py tests/test_cli.py -k "freshness or gitlab"` — **14 passed, 30 deselected**.
- `git diff --check` — **passed** (no whitespace errors).

Commit: `feat: add GitLab knowledge freshness report` (final commit hash is
reported at handoff).

Concern: Git emitted normal LF-to-CRLF working-copy warnings while inspecting
the three edited text files; `git diff --check` passed.
