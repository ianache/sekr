# SEKR Experiment Pack v0.1 — P0 + P1 Design

**Date:** 2026-09-08  
**Status:** Approved design  
**Scope:** P0 experimental definition and P1 minimum knowledge model  
**Corpus:** Existing curated fixture `data/coder_activation.json`

## Objective

Close the P0 and P1 milestones of the SEKR PoC with a small, executable and
reproducible experiment pack. The pack will formalize the Tenant/Coder
activation case, define the evaluation oracle and acceptance thresholds, and
document the minimum knowledge ontology implemented by the current JSON/SQLite
runtime.

Neo4j, automatic repository ingestion, Knowledge Delta execution and
Knowledge-as-Tests execution remain outside this increment. They are P2, P5
and P6 work respectively.

## P0 — Experimental definition

### Case

The controlled case is Tenant/Coder activation and deactivation:

> Activate and deactivate individual Tenant Coder values while ensuring that
> active-value queries exclude inactive values and deactivation preserves
> history.

The input corpus is the curated fixture in
`data/coder_activation.json`. Its evidence paths are controlled references;
the experiment does not claim to perform live repository ingestion.

### Hypotheses

- **H1 — Context precision:** the SEKR Compiler retrieves more relevant
  artifacts than normalized textual token overlap at the same budget.
- **H2 — Critical coverage:** the Compiler retrieves all artifacts marked
  critical by the human oracle.
- **H3 — Traceability:** selected artifacts and attached facts retain source
  evidence, confidence and freshness information.
- **H4 — Reproducibility:** repeated executions with the same fixture, oracle,
  task and budget produce identical serialized results.

Knowledge Delta and Knowledge-as-Tests are not evaluated as P0 outcomes; they
remain future milestones even though the broader DRP includes them.

### Oracle

`data/oracle/coder_activation.json` is the evaluation oracle. It contains:

- expected artifact IDs;
- critical artifact IDs, which must be a subset of expected IDs.

The Compiler output must not expose oracle contents. Evaluation may read the
oracle after compilation and reports metrics rather than oracle IDs.

### Acceptance criteria

For budget `K = 6`:

1. Compiler `precisionAtK` is greater than or equal to baseline
   `precisionAtK`.
2. Compiler `criticalRecall` equals `1.0`.
3. Compiler `falsePositiveRate` is less than or equal to baseline
   `falsePositiveRate`.
4. Repeated Compiler runs are byte-for-byte equivalent after canonical JSON
   serialization.
5. The Compiler returns no more than `K` selected items and reports omitted
   candidates when truncation occurs.
6. Selected artifacts and attached facts preserve evidence and confidence;
   unsupported evidence is surfaced as `UNKNOWN`, conflicted, or a warning.
7. Compiler output does not contain `expected_artifact_ids` or
   `critical_artifact_ids`.

The current fixture is expected to demonstrate: Compiler precision `1.0`,
critical recall `1.0`, false-positive rate `0.0`; baseline precision
`0.8333333333333334`, critical recall `0.75`, and false-positive rate `0.5`.

### Protocol

1. Create a fresh SQLite database.
2. Load `data/coder_activation.json`.
3. Validate the loaded database.
4. Execute the normalized-token baseline and deterministic Compiler with the
   same task and budget.
5. Execute the Compiler twice to test reproducibility.
6. Compare metrics against the oracle.
7. Store the command inputs, environment/version information, serialized
   outputs and a human-readable report.

## P1 — Minimum knowledge model

### Entity catalog

The ontology defines the following entity types:

| Entity | Runtime status | Purpose |
|---|---|---|
| `Requirement` | Supported artifact type | Expected behavior or constraint |
| `Feature` | Supported | User/business capability |
| `Component` | Supported | Architectural/runtime unit |
| `Symbol` | Supported | Class, function, service or repository symbol |
| `Endpoint` | Supported | API or externally exposed operation |
| `Table` | Supported | Persistence/schema object |
| `Test` | Supported | Verification artifact |
| `ADR` | Supported as document artifact | Architectural decision |
| `Document` | Supported | Evidence-bearing documentation |
| `KnowledgeFact` | Supported in facts table | Evidence-backed statement about an artifact |
| `Repository` | Supported | Persistence or source repository reference |
| `Change` | Defined only | Future diff/change unit for P5 |
| `KnowledgeRule` | Defined only | Future executable rule for P6 |

`Change` and `KnowledgeRule` are deliberately documented but are not added as
loadable SQLite types in P1.

### Relationships

The minimum relationship vocabulary is:

| Relationship | Meaning |
|---|---|
| `IMPLEMENTS` | Requirement is implemented by a feature/component |
| `IMPLEMENTED_BY` | Feature is implemented by a symbol/component |
| `EXPOSED_BY` | Feature is exposed by an endpoint |
| `PERSISTS_TO` | Feature/component persists to a table/repository |
| `VERIFIED_BY` | Feature or symbol is verified by a test |
| `CONSTRAINED_BY` | Feature/component is constrained by an ADR/document |
| `DEPENDS_ON` | Artifact depends on another artifact |
| `CALLS` | Symbol or endpoint invokes another symbol |
| `DOCUMENTED_BY` | Artifact is described by a document |
| `AFFECTS` | Future change affects an artifact or fact |
| `EVIDENCED_BY` | Fact or artifact is supported by a document/evidence source |

The current fixture uses a subset of these relations and records explicit
source evidence and confidence for every relation.

### Fact and provenance contract

Every fact contains an ID, statement, source, evidence list, confidence,
freshness, source version, validity start, scope and optional owner. Confidence
values are `VERIFIED`, `APPROVED`, `INFERRED`, `STALE`, `CONFLICTED` and
`UNKNOWN`.

`VERIFIED` and `APPROVED` require non-empty evidence. Evidence-free content
must be normalized to `UNKNOWN` or `CONFLICTED` and must never be presented as
verified.

### Task profile contract

A task profile maps a bounded task to normalized terms, expected artifact
types and expected artifact IDs. It supports deterministic retrieval and
provides the bridge between the P0 task and the P1 ontology.

## Runtime mapping

The P1 reference implementation remains the current local JSON/SQLite model:

- JSON collections: `metadata`, `artifacts`, `relations`, `facts`,
  `task_profiles`;
- SQLite tables: `dataset_metadata`, `artifacts`, `relations`, `facts`,
  `task_profiles`;
- CLI validation: `sekr.exe dataset load` followed by
  `sekr.exe dataset validate`;
- evaluation: `sekr.exe context evaluate --case coder-activation`.

Neo4j storage, generic ingestion and new runtime entities are intentionally
not required for P1 completion.

## Experiment pack outputs

The implementation phase will create an `experiment-pack/v0.1/` directory
containing:

- `README.md` — exact setup and execution protocol;
- `ontology.md` — entity, relationship, provenance and confidence catalog;
- `hypotheses.md` — P0 hypotheses and acceptance criteria;
- `expected-results.json` — canonical expected metrics;
- `run-experiment.ps1` — reproducible Windows execution script;
- `reports/EXPERIMENT_REPORT.md` — generated comparison and decision report.

The existing dataset and oracle remain the canonical inputs and are referenced
without duplicating their contents.

## Verification

P0/P1 is complete when:

- the fixture loads and validates through the standalone CLI;
- all acceptance criteria pass automatically;
- the ontology catalog matches the runtime artifact/relation vocabulary;
- the protocol can be repeated from a fresh database;
- the report contains baseline, Compiler and reproducibility results;
- no P2/P5/P6 implementation is required to run the pack.

## Explicit non-goals

- Live source/repository ingestion.
- Neo4j or another graph database.
- MCP integration.
- Git diff analysis and Knowledge Delta.
- Executable Knowledge-as-Tests rules.
- Agent/harness treatment runs beyond the deterministic baseline/Compiler
  retrieval comparison.
