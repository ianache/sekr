# SEKR P2 Ingestion and Neo4j Design

**Date:** 2026-09-09
**Status:** Approved design
**Scope:** P2 ingestion and Neo4j persistence
**Depends on:** P0/P1 JSON dataset, SQLite validator, and Context Compiler

## Objective

Implement the first reproducible P2 vertical slice: load the existing
`data/coder_activation.json` dataset, validate its references and provenance,
transform it into a canonical graph representation, and persist it in Neo4j.
The operation must be repeatable without duplicating nodes or relationships.

P2 does not change the SQLite runtime or the behavior of `ContextCompiler`.
SQLite remains the P1 reference implementation and Neo4j is an additional
projection of the same validated knowledge dataset.

## Scope and non-goals

Included:

- JSON dataset ingestion from a local path.
- Reuse of the existing dataset validation contract.
- Neo4j persistence through a dedicated adapter.
- Deterministic counts and a dry-run mode.
- Stable identifiers, provenance, confidence, and dataset metadata.
- Structured errors for invalid input and persistence failures.

Excluded from P2:

- Automatic repository, PDF, Google Drive, or universal source ingestion.
- Incremental file watching or change detection.
- Replacing SQLite as the compiler data source.
- MCP, Knowledge Delta, Knowledge-as-Tests, or agent integration.
- Neo4j schema migrations or production deployment automation.

## Architecture

The ingestion flow has four stages:

1. `ingest.py` reads the JSON source and invokes the existing domain/database
   validation rules before any write is attempted.
2. A canonical graph projection converts the validated collections into typed
   node and relationship records without embedding Cypher or Neo4j objects.
3. `neo4j.py` receives that projection and writes it using parameterized Cypher
   and `MERGE` on stable keys.
4. `cli.py` exposes the operation and serializes success or `StructuredError`
   results as JSON, following the existing CLI conventions.

The projection layer is deliberately independent of the Neo4j driver. This
allows unit tests to verify the graph contract and idempotency without a live
database, while the adapter remains replaceable.

## Graph contract

Every node has a stable `id` and `kind` property. The initial labels and
properties are:

| Label | Stable key | Required properties |
|---|---|---|
| `Dataset` | `id = metadata.version` | `version`, `source_commit`, `generated_at`, `description` |
| `Artifact` | `id = artifact.id` | `artifact_type`, `title`, `description`, `path`, `evidence`, `confidence` |
| `Fact` | `id = fact.id` | `statement`, `source`, `evidence`, `confidence`, `freshness`, `source_version`, `valid_from`, `scope`, `owner` |
| `TaskProfile` | `id = profile.id` | `name`, `terms`, `expected_artifact_types` |

Relationships are directed and use a single safe Neo4j relationship type
`RELATES_TO` with a `relation_type` property. This preserves the source
dataset's relation vocabulary without interpolating untrusted values into
Cypher. Each relationship also stores `id`, `evidence`, and `confidence`.

The following structural relationships are created:

- `Dataset-[:HAS_ARTIFACT]->Artifact`
- `Artifact-[:HAS_FACT]->Fact`
- `Dataset-[:HAS_PROFILE]->TaskProfile`
- `TaskProfile-[:EXPECTS_ARTIFACT]->Artifact`
- `Artifact-[:RELATES_TO {relation_type: ...}]->Artifact`

All writes use `MERGE` keyed by IDs. Re-running the same dataset updates
properties and does not create duplicate nodes or relationships. A relation
whose source or target does not exist is rejected before persistence.

## Interfaces

The projection module will expose immutable, serializable records and:

```python
def build_graph_projection(dataset_path: str | Path) -> GraphProjection:
    """Validate a JSON dataset and return its canonical graph projection."""
```

The Neo4j adapter will expose:

```python
def write_projection(
    projection: GraphProjection,
    *,
    uri: str,
    user: str,
    password: str,
) -> IngestSummary:
    """Persist one projection atomically and return deterministic counts."""
```

The CLI command will be:

```text
sekr ingest neo4j --source data/coder_activation.json \
  --uri bolt://localhost:7687 --user neo4j --password <password>
```

`--dry-run` requires no driver connection and returns projection counts,
dataset version, and validation status. Credentials are accepted only as
command arguments or environment-backed CLI options and are never included in
normal output or error details.

## Error handling

- Missing, unreadable, or malformed JSON produces `INVALID_DATASET`.
- Invalid artifact/relation/fact/profile records reuse existing structured
  validation codes and include the affected identifier when available.
- Missing relation/profile references produce `INVALID_REFERENCE` before any
  Neo4j session is opened.
- Driver connection and transaction failures produce `NEO4J_CONNECTION_ERROR`
  or `NEO4J_WRITE_ERROR`, with the underlying message sanitized from secrets.
- A failed write is rolled back as one transaction; the CLI exits non-zero and
  emits the existing structured JSON error shape.

## Verification

P2 is complete when:

- The current fixture produces the expected node and relationship counts.
- The projection is deterministic for repeated reads of the same JSON.
- A fake-driver test proves a second write uses stable `MERGE` keys and does
  not rely on generated IDs.
- `--dry-run` validates the fixture without requiring Neo4j.
- Invalid references fail before any write call.
- An optional live Neo4j test passes when `SEKR_NEO4J_URI`,
  `SEKR_NEO4J_USER`, and `SEKR_NEO4J_PASSWORD` are provided, and is skipped
  otherwise.
- The pre-existing P0/P1 suite remains green.
