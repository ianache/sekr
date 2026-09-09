# SEKR P0 hypotheses and acceptance

## Case and boundary

The controlled case is Tenant/Coder activation and deactivation: activate and
deactivate individual Tenant Coder values while active-value queries exclude
inactive values and deactivation preserves history. The input is the curated
`data/coder_activation.json` fixture. The evaluation oracle is
`data/oracle/coder_activation.json`; it is read only for evaluation and is not
part of Compiler output.

The experiment compares the deterministic SEKR Compiler with normalized
text-token overlap at the same budget, `K = 6`.

## Hypotheses

- **H1 — Context precision:** the SEKR Compiler retrieves more relevant
  artifacts than normalized textual token overlap at the same budget.
- **H2 — Critical coverage:** the Compiler retrieves all artifacts marked
  critical by the human oracle.
- **H3 — Traceability:** selected artifacts and attached facts retain source
  evidence, confidence, and freshness information.
- **H4 — Reproducibility:** repeated executions with the same fixture, oracle,
  task, and budget produce identical serialized results.

Knowledge Delta and Knowledge-as-Tests are not evaluated as P0 outcomes; they
remain future milestones.

## Approved acceptance rules

For budget `K = 6`, the experiment is accepted when:

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

The canonical fixture expectation is Compiler precision `1.0`, critical recall
`1.0`, false-positive rate `0.0`; baseline precision
`0.8333333333333334`, critical recall `0.75`, and false-positive rate `0.5`.
