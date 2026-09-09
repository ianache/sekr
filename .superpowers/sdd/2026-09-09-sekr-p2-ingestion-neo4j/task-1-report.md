# Task 1 report — driver-independent graph projection

## Changed files

- `src/sekr/ingest.py`: added frozen graph projection records and validated,
  deterministic JSON-to-graph conversion without Neo4j imports.
- `src/sekr/db.py`: exposed `validate_dataset_json(data)` and routed the
  existing SQLite loader through it without changing the raw validation rules.
- `tests/test_ingest.py`: added fixture count/version, determinism, invalid
  relation reference, and graph-property contract coverage.

## Commit

- `a6acbdfe52d3b928388e5227f5ed1faf959a30f2`
  `feat: add deterministic sekr graph projection`

## TDD evidence

The initial projection test run failed during collection with
`ModuleNotFoundError: No module named 'sekr.ingest'`. After the minimal
projection implementation, `pytest -q tests/test_ingest.py` passed with
`3 passed`. A subsequent graph-contract test failed with a missing `kind`
property, then passed after node and structural-relationship properties were
completed.

## Tests run

- `pytest -q tests/test_ingest.py` → `4 passed in 0.10s`
- `pytest -q tests/test_db.py` → `67 passed in 6.12s`
- `pytest -q` → `135 passed in 27.11s`

## Self-review findings

- The projection validates the entire UTF-8 JSON dataset before constructing
  a graph record; dangling references continue to raise `INVALID_REFERENCE`.
- Collections are sorted by ID before projection. The fixture produces one
  dataset node, 12 non-dataset nodes, and 25 directed relationships.
- Node source fields, provenance, confidence, metadata, and task-profile
  expected artifact IDs are retained. Optional absent node fields are made
  explicit as `None` for later adapter handling.
- The module is driver-independent: it imports no Neo4j package or driver
  object. SQLite schema, CLI, and ContextCompiler remain untouched.

## Concerns

None. Structural relationship keys and properties are deterministic and use
the fixed graph-contract vocabulary for the later Neo4j adapter.

## Fix round 1

### Changes

- Canonicalized each task profile's `expected_artifacts` both in the profile
  node property and when producing profile-to-artifact relationships. Reordered
  source lists now produce an equal projection.
- Changed structural relationship evidence from `[]` to `None`, representing
  absent provenance without an empty Neo4j property value.
- Strengthened fixture coverage with exact 9 Artifact / 2 Fact / 1
  TaskProfile node assertions and exact 9 / 2 / 1 / 7 / 6 relationship split
  assertions.
- Added coverage for dataset metadata, fact source metadata, canonical profile
  expected artifacts, and absent optional artifact and fact values.

### Commit

- `0ea111ff5a00a343d4dfa8ae3e35e84bf3c386bc`
  `fix: canonicalize sekr graph projection`

### TDD evidence

Before the production change, `pytest -q tests/test_ingest.py` produced three
expected failures: a reordered profile artifact list changed `nodes` and
`relationships`; structural evidence was `[]` instead of `None`; and the
optional-value test fixture needed to account for its already-absent
`valid_from` field. The corrected test fixture then continued to fail only on
the production ordering and structural-evidence behavior until those changes
were applied.

### Verification

- `pytest -q tests/test_ingest.py` → `6 passed in 0.14s`
- `pytest -q` → `137 passed in 27.54s`

### Self-review

- Profile node properties and nested profile edges now sort artifact IDs, so
  source order cannot affect projection equality.
- Structural edges consistently carry `None` for absent evidence and retain
  their fixed relation type and `UNKNOWN` confidence.
- The new assertions cover all requested fixture splits and the metadata,
  profile, fact, and optional-value preservation contracts.
- Scope remains limited to `src/sekr/ingest.py` and `tests/test_ingest.py`;
  no SQLite, CLI, ContextCompiler, or Neo4j code changed.

### Concerns

None.
