# SEKR Experiment Report

## Case

- Case name: `coder-activation`
- Controlled task: activate and deactivate Tenant Coder values while active
  queries exclude inactive values and history is preserved.

## Inputs

- Executable: the standalone `sekr.exe` probe supplied from the original
  checkout.
- Dataset: `data/coder_activation.json`
- Evaluation oracle: `data/oracle/coder_activation.json` (used only by the
  evaluator; its contents are not reproduced here).
- Expected results: `experiment-pack/v0.1/expected-results.json`
- Task: `activate coder values`
- Budget: `K = 6`

## Commands

```text
sekr.exe dataset load --db <fresh-output>/knowledge.sqlite --source data/coder_activation.json
sekr.exe dataset validate --db <fresh-output>/knowledge.sqlite
sekr.exe context compile --db <fresh-output>/knowledge.sqlite --task "activate coder values" --budget 6
sekr.exe context evaluate --db <fresh-output>/knowledge.sqlite --case coder-activation --budget 6 --oracle-path data/oracle/coder_activation.json
```

## Baseline metrics

- precisionAtK: 0.8333333333333334
- criticalRecall: 0.75
- falsePositiveRate: 0.5
- contextSize: 6
- candidateCount: 9

## Compiler metrics

- precisionAtK: 1.0
- criticalRecall: 1.0
- falsePositiveRate: 0.0
- contextSize: 6
- candidateCount: 9

## Compilation checks

- omittedCount: 2
- warnings: budget_truncated
- selected items: 6
- All selected artifacts and attached facts retained valid evidence and
  confidence provenance.

## Reproducibility

- Deterministic repeated Compiler output: True
- Standalone executable SHA-256:
  `211C13406BBCB66347BF4766C5E19852907C44234104169BB3A5683BD3B3D5F9`
- Dataset SHA-256:
  `B718E04B6BC11D9078FD4B2C88A3BD7353622E485AB2ABF943D70363CF04B687`
- Evaluator input SHA-256:
  `4B0375AD7840ADB999A3EAACE1B4ECF5678824B34939CA93CFDD59A2A2D56B44`

## Acceptance results

- PASS: Compiler precisionAtK is at least baseline.
- PASS: Compiler criticalRecall equals the approved threshold.
- PASS: Compiler falsePositiveRate is at most baseline.
- PASS: Compiler result is reproducible.
- PASS: Compiler context is within budget.
- PASS: Truncation reports omittedCount and budget_truncated.
- PASS: Selected artifacts and facts retain valid evidence/confidence provenance.
- PASS: Evaluation output does not disclose evaluation-only data.
- PASS: Compiler fixture metrics match expected results.
- PASS: Baseline fixture metrics match expected results.

## Decision

GO
