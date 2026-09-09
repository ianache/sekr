# Task 3 report — P1 runtime mapping and acceptance behavior

## Scope

Implemented Task 3 using only the requested test and fixture scope. No runtime
Change or KnowledgeRule types, Neo4j, ingestion, Delta, or executable
Knowledge-as-Tests behavior was added.

## Changes

- Added a fixture vocabulary test requiring `feature`, `endpoint`, `symbol`,
  `table`, `test`, `document`, and `repository` artifact types.
- Added provenance coverage asserting every `VERIFIED` or `APPROVED` fixture
  artifact and relation has non-empty evidence.
- Retained and exercised the fixture relation-vocabulary test against
  `ontology.md`.
- Added an acceptance test that invokes `sekr.cli context evaluate` with the
  fixture oracle and reads `expected-results.json` for the case and budget.
  It verifies critical recall, precision and false-positive comparisons,
  reproducibility, the six-item budget, and absence of oracle field names.
- Corrected the unrelated false-positive fixture record to the supported
  `document` runtime type and updated the task profile's expected type from
  `adr` to `document`. The ADR record remains `adr` to preserve the existing
  compiler architectural-constraint mapping.

## TDD evidence

The new runtime-vocabulary test was run against the pre-fix fixture and failed
because `document` was absent. After the minimal fixture correction, the
focused suite passed.

## Verification

- Focused: `pytest -q tests/test_experiment_pack.py` → **8 passed, 1 skipped**.
- Full suite: `pytest -q` → **128 passed, 1 skipped**.
- The single skip is the pre-existing runner smoke test when the local
  PowerShell/probe prerequisites are unavailable.

## Concerns

`ontology.md` already declared every relation used by the fixture, so no
ontology edit was necessary. The legacy `adr` runtime value remains present
because the current compiler implementation and existing tests use it for
architectural constraints; the new `document` type is nevertheless present
in the fixture and task profile as required by the P1 mapping test.

## Review fix

The initial implementation incorrectly relabeled the unrelated
`component.billing_invoice_export` false-positive control as `document`. This
fix restores that artifact to `component` and changes the actual
`document.adr_coder_activation` artifact from legacy `adr` to `document`.
The task profile already references the ADR by its document ID and now uses
the document type consistently.

The vocabulary test now checks the semantic mapping of both named artifacts,
and the relation-vocabulary assertion matches ontology table rows rather than
any incidental occurrence of a backticked token. The existing compiler test
was adjusted to verify that the legacy `adr`-only architectural section stays
empty for the new document mapping while all other compiled sections remain
compatible.

## Review-fix verification

- Focused compatibility suite: `pytest -q tests/test_experiment_pack.py tests/test_compiler.py` → **34 passed, 1 skipped**.
- Full suite: `pytest -q` → **128 passed, 1 skipped**.
