# SEKR Experiment Report

## Inputs

- Executable: `C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\build-standalone-probe-20260908\dist\sekr.exe`
- Dataset: `C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\data\coder_activation.json`
- Oracle: `C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\data\oracle\coder_activation.json`
- Expected results: `C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\expected-results.json`
- Output directory: `C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\reports\task-4-fix-run-3`

## Commands

```text
C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\build-standalone-probe-20260908\dist\sekr.exe dataset load --db C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\reports\task-4-fix-run-3\knowledge.sqlite --source C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\data\coder_activation.json
C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\build-standalone-probe-20260908\dist\sekr.exe dataset validate --db C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\reports\task-4-fix-run-3\knowledge.sqlite
C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\build-standalone-probe-20260908\dist\sekr.exe context compile --db C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\reports\task-4-fix-run-3\knowledge.sqlite --task activate coder values --budget 6
C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\build-standalone-probe-20260908\dist\sekr.exe context evaluate --db C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\experiment-pack\v0.1\reports\task-4-fix-run-3\knowledge.sqlite --case coder-activation --budget 6 --oracle-path C:\Users\ianache\Desktop\DATA\01-DOCUMENTOS\02-PROYECTOS\114-KB-Comsatel\SEKR-PoC\.worktrees\sekr-p0-p1-experiment-pack\data\oracle\coder_activation.json
```

## Baseline metrics

- precisionAtK: 0.8333333333333334
- criticalRecall: 0.75
- falsePositiveRate: 0.5

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

## Reproducibility

- Deterministic repeated compiler output: True

## Acceptance results

- PASS: Compiler precisionAtK is at least baseline
- PASS: Compiler criticalRecall equals expected threshold
- PASS: Compiler falsePositiveRate is at most baseline
- PASS: Compiler result is reproducible
- PASS: Compiler context is within budget
- PASS: Truncation reports omittedCount and budget_truncated
- PASS: Selected artifacts and facts retain valid evidence/confidence provenance
- PASS: Compiler and evaluation output do not expose oracle data
- PASS: Compiler fixture metrics match expected results
- PASS: Baseline fixture metrics match expected results

## Decision

GO
