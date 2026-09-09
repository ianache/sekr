# SEKR-PoC v0.1 — Context Compiler Design

**Date:** 2026-09-07  
**Status:** Approved design  
**Scope:** Context Compiler only

## Objective

Validate that SEKR can deliver the minimum relevant and traceable context for a concrete engineering task, with less noise than a simple textual baseline.

The sole evaluation case is the Tenant microservice change for activating/deactivating individual Coder values and excluding inactive values from active queries.

## Scope and boundaries

### Included

- A local CLI executable.
- A versioned, curated knowledge dataset.
- SQLite as the initial storage layer.
- Basic task-intent interpretation.
- Candidate retrieval from structured knowledge and relations.
- Explainable, reproducible ranking.
- Configurable context budget.
- `ContextPackage` JSON output with evidence, confidence, and inclusion rationale.
- Dataset validation and evaluation against a simple textual baseline.
- Metrics for precision@K, recall of critical artifacts, context size, and false positives.

### Deferred

- Automatic repository ingestion.
- Neo4j storage.
- MCP server and direct Codex integration.
- Embeddings or vector search.
- Knowledge Delta.
- Knowledge-as-Tests.
- Automatic modification of the Tenant repository.

## Architecture and data flow

```text
curated dataset → SQLite → task interpretation
                         → candidate retrieval
                         → explainable ranking
                         → budget application
                         → ContextPackage + evaluation report
```

The compiler is local and deterministic for the same dataset version, task, configuration, and budget. The storage layer is isolated behind a small repository interface so it can later be replaced by Neo4j without changing the compiler contract.

## Knowledge model

SQLite will contain at least:

- `artifacts`: features, symbols, endpoints, tables, tests, and documents;
- `relations`: relationships such as `IMPLEMENTS`, `CALLS`, `PERSISTS_TO`, `VERIFIED_BY`, and `CONSTRAINED_BY`;
- `facts`: statements with source, evidence, confidence, and freshness;
- `task_profiles`: terms and expected artifacts for the experimental task;
- `dataset_metadata`: dataset version, source commit, and generation timestamp.

Every returned item must retain provenance and an explanation, for example:

```json
{
  "id": "symbol.coder_value_service",
  "relevanceScore": 0.92,
  "confidence": "APPROVED",
  "evidence": ["tenant/src/..."],
  "whyIncluded": ["matches_domain", "related_to_active_filter"]
}
```

Confidence values must not imply verification when evidence is absent. Unsupported or contradictory facts are returned with an explicit `UNKNOWN` or conflict state.

## Compiler behavior

The compiler accepts a natural-language task and produces a `ContextPackage` containing requirements, architectural constraints, relevant symbols, execution flows, persistence/schema, tests, risks, evidence, confidence, conflicts, and budget information.

Ranking combines:

1. task-intent and domain-term matches;
2. relational proximity to the target feature;
3. artifact type relevance;
4. evidence quality;
5. fact confidence and freshness.

The compiler applies the configured budget after ranking. It must record omitted candidates or a summary of truncation so evaluation can distinguish intentional budget limits from retrieval failures.

## CLI contract

Initial commands:

- `dataset validate`: validate schema, identifiers, relation endpoints, provenance, and required metadata;
- `context compile --task <file-or-text> --budget <n>`: produce a `ContextPackage`;
- `context evaluate --case coder-activation`: compare compiler output with the hidden evaluation oracle and the textual baseline.

The CLI returns machine-readable JSON and non-zero exit codes for invalid input or invalid datasets. A valid but empty result remains a structured `ContextPackage` containing an explicit absence/conflict signal.

## Evaluation

The baseline performs simple textual matching over the same curated artifacts. The compiler is evaluated against a hidden human oracle containing relevant files/symbols, expected dependencies, tests, and documents.

Minimum metrics:

- precision@K of retrieved artifacts;
- recall of critical artifacts;
- context size in items/bytes;
- false-positive rate;
- reproducibility across repeated runs.

Minimum test coverage:

- dataset validation;
- expected ranking for the activation/deactivation task;
- budget enforcement and truncation reporting;
- provenance and confidence propagation;
- missing-evidence behavior;
- baseline/compiler comparison.

## Error handling and safety

- Empty or malformed task: structured input error.
- Inconsistent dataset: validation error; compilation must not proceed silently.
- Missing evidence: mark the item `UNKNOWN` or conflicted; never present it as verified.
- Budget too small: return a partial package with a warning.
- No candidates: return a valid package with an explicit absence signal.

The curated dataset must exclude secrets and unauthorized source content. The compiler must not send source or knowledge data to external services.

## Success criterion

The PoC is successful if the compiler shows materially better relevance and traceability than the textual baseline for the Tenant/Codifier activation case while respecting a configured context budget and producing reproducible evidence-backed output.
