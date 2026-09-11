# SEKR P7.1 Provenance and Freshness Design

**Status:** Proposed

**Goal:** Make knowledge provenance explicit and calculate deterministic freshness and verification states without silently changing approved knowledge.

## Scope

P7.1 extends the existing SEKR dataset and canonical knowledge snapshot with provenance fields and a read-only freshness report. The implementation uses both declared source dates and observed content hashes:

- Declared dates provide the source's claimed validity window.
- Content hashes detect whether referenced evidence changed since observation.
- Freshness reports identify stale, changed, unverified, and conflicted records.
- Existing `knowledge-check` policies remain responsible for deciding whether CI blocks.

P7.1 does not introduce a provenance database, automatic approval, remote crawling, or Neo4j schema migration.

## Provenance model

Provenance is represented as optional fields on artifacts, facts, and relations where the source data supports them:

```json
{
  "source": "ADR 004",
  "evidence": ["tenant/docs/adr/004-coder-activation.md:12-20"],
  "source_version": "0.1",
  "content_hash": "sha256:...",
  "observed_at": "2026-09-11T12:00:00Z",
  "valid_from": "2026-09-01T00:00:00Z",
  "valid_until": "2026-12-31T23:59:59Z"
}
```

`content_hash` is a SHA-256 hash of the canonical UTF-8 source content used for verification. Hashes are compared only when the referenced evidence resolves to a readable local file. `observed_at` is metadata for an observation and is not generated during ordinary deterministic snapshot creation.

## Freshness states

The freshness evaluator assigns one state per record using this precedence:

1. `conflicted` — the record has an explicit `CONFLICTED` confidence or incompatible provenance values.
2. `unverified` — required evidence is absent, unreadable, or has no prior content hash.
3. `changed` — the current evidence hash differs from the stored `content_hash`.
4. `stale` — `valid_until` is before the evaluation time, or the source declares a stale status.
5. `current` — evidence is readable, the hash matches, and the validity window is active.

Evaluation time is supplied explicitly with `--as-of ISO-8601` and defaults to the current UTC clock only for interactive use. CI must pass a fixed value when reproducibility is required.

## CLI contract

Add:

```text
sekr knowledge-freshness --input PATH [--as-of ISO-8601] [--output PATH]
```

The input may be a canonical snapshot or a validated SEKR dataset. The output is deterministic for a fixed input and `--as-of`:

```json
{
  "as_of": "2026-09-11T12:00:00Z",
  "valid": false,
  "counts": {"current": 1, "stale": 0, "changed": 1, "unverified": 0, "conflicted": 0},
  "records": [
    {"kind": "Fact", "key": "fact.example", "state": "changed", "reasons": ["CONTENT_HASH_MISMATCH"]}
  ]
}
```

`valid` is true only when every evaluated record is `current`. Invalid input produces the existing structured error contract and exit code `1`; a valid report with non-current records also exits `1` unless a later policy integration explicitly permits it.

## Data flow

1. Read and validate the dataset or snapshot.
2. Normalize records and extract provenance/evidence references.
3. Resolve local evidence paths safely relative to the input/repository root.
4. Compute current hashes without executing source files.
5. Apply the state precedence rules using the explicit evaluation time.
6. Emit sorted counts and records, or write the exact JSON bytes with `--output`.

No step mutates the input, approved baseline, SQLite database, or Neo4j.

## CI integration

P7.1 adds a report-producing freshness job to the existing GitLab workflow after the knowledge check. The job uses a fixed `SEKR_KNOWLEDGE_AS_OF` variable in CI and publishes `.sekr/knowledge-freshness.json` as an artifact. Whether freshness blocks the pipeline remains controlled by the existing policy layer and is outside automatic baseline updates.

## Errors and safety

- Missing or malformed provenance fields use `INVALID_PROVENANCE` with a stable field and record detail.
- Unreadable evidence produces `unverified`, not a guessed hash.
- Evidence paths are constrained to the permitted input/repository root.
- Hashing reads bytes only; it never imports or executes referenced code.
- Passwords, environment secrets, and absolute local paths are excluded from reports.

## Testing and acceptance

- Unit tests cover each state and precedence rule with fixed `--as-of` values.
- Tests cover matching and mismatching hashes, validity windows, missing evidence, conflicts, and deterministic ordering.
- CLI tests cover dataset/snapshot input, structured errors, `--output`, and exit codes.
- GitLab contract tests verify the freshness job, fixed evaluation variable, artifact retention, and non-mutating behavior.
- Acceptance requires identical output for repeated runs with identical input and `--as-of`, and no changes to approved baseline files.
