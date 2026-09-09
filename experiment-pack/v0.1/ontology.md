# SEKR P1 ontology v0.1

The ontology is the documentation contract for the current local JSON/SQLite
model. Loadable runtime collections are `metadata`, `artifacts`, `relations`,
`facts`, and `task_profiles`; `Change` and `KnowledgeRule` are documentation-only
in this increment.

## Entities

| Entity | Runtime status | Purpose |
| --- | --- | --- |
| `Requirement` | Supported artifact type | Expected behavior or constraint |
| `Feature` | Supported | User or business capability |
| `Component` | Supported | Architectural or runtime unit |
| `Symbol` | Supported | Class, function, service, or repository symbol |
| `Endpoint` | Supported | API or externally exposed operation |
| `Table` | Supported | Persistence or schema object |
| `Test` | Supported | Verification artifact |
| `ADR` | Supported as document artifact | Architectural decision |
| `Document` | Supported | Evidence-bearing documentation |
| `KnowledgeFact` | Supported in the facts table | Evidence-backed statement about an artifact |
| `Repository` | Supported | Persistence or source repository reference |
| `Change` | Documentation-only | Future diff/change unit for Knowledge Delta (P5) |
| `KnowledgeRule` | Documentation-only | Future executable rule for Knowledge-as-Tests (P6) |

## Relationship vocabulary

| Relationship | Meaning |
| --- | --- |
| `IMPLEMENTS` | Requirement is implemented by a feature or component |
| `IMPLEMENTED_BY` | Feature is implemented by a symbol or component |
| `EXPOSED_BY` | Feature is exposed by an endpoint |
| `PERSISTS_TO` | Feature or component persists to a table or repository |
| `VERIFIED_BY` | Feature or symbol is verified by a test |
| `CONSTRAINED_BY` | Feature or component is constrained by an ADR or document |
| `DEPENDS_ON` | Artifact depends on another artifact |
| `CALLS` | Symbol or endpoint invokes another symbol |
| `DOCUMENTED_BY` | Artifact is described by a document |
| `AFFECTS` | Future change affects an artifact or fact |
| `EVIDENCED_BY` | Fact or artifact is supported by a document or evidence source |

The fixture stores relation vocabulary in lowercase (for example,
`exposed_by`, `calls`, and `persists_to`); these values map directly to the
canonical names above. The fixture uses a subset of the vocabulary.

## Facts and provenance

Every fact contains an ID, statement, source, evidence list, confidence,
freshness, source version, validity start, scope, and optional owner. Artifacts
and relations also carry source evidence and confidence.

Allowed confidence values are `VERIFIED`, `APPROVED`, `INFERRED`, `STALE`,
`CONFLICTED`, and `UNKNOWN`.

`VERIFIED` and `APPROVED` require non-empty evidence. Evidence-free content is
normalized to `UNKNOWN` or `CONFLICTED` and must never be presented as verified.
Unsupported evidence must be surfaced as `UNKNOWN`, conflicted, or a warning.
Evidence references are controlled paths and line ranges, not claims of live
repository ingestion.

## Task profile

A task profile maps a bounded task to normalized terms, expected artifact types,
and expected artifact IDs. It provides deterministic retrieval while keeping
evaluation oracle data separate from Compiler output.
