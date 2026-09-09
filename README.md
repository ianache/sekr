# SEKR Context Compiler

SEKR is a local, deterministic proof of concept for compiling a bounded context package for the sole supported case: Tenant/Coder activation and deactivation. It reads a curated JSON dataset from SQLite and returns evidence-backed artifacts for a task. It uses no external services.

## Setup

Requires Python 3.11 or later. Create an environment, install the project with its test dependency, and load the curated fixture:

```powershell
python -m pip install -e ".[test]"
New-Item -ItemType Directory -Force .sekr
sekr dataset load --db .sekr/knowledge.sqlite --source data/coder_activation.json
```

## Dataset format

`data/coder_activation.json` has metadata plus `artifacts`, `relations`, `facts`, and `task_profiles`. Metadata requires non-blank `version`, `source_commit`, and `generated_at` strings. Evidence entries and task-profile terms/references must be non-blank strings in arrays; referenced artifacts must exist. Evidence-free records are allowed only with `UNKNOWN` or `CONFLICTED` confidence. These checks apply both when loading JSON and when validating SQLite, including validation inside the public `ContextCompiler.compile()` method.

Every returned artifact retains its own evidence and confidence. Its `facts` array preserves each attached fact's ID, statement, source, evidence, confidence, freshness, source version, validity, scope, and owner. In `requirements`, artifact references remain strings and fact statements are now structured fact objects. Consumers of the previous string-only section must handle these objects. Evidence-free selected facts generate `missing_evidence` even when their artifact has evidence.

Ranking averages confidence quality and evidence presence across an artifact and its attached facts. Freshness uses the fraction of attached facts marked `current` (zero for no facts). The fixed component weights remain in `whyIncluded`. All attached facts contribute because they are included in the candidate's context. Scoring uses the loaded fact batch, including an empty batch; calling `score()` without a fact mapping scores artifact quality only and performs no fact queries.

The evaluation oracle at `data/oracle/coder_activation.json` is intentionally separate: it contains only expected artifact IDs and critical-artifact IDs, and compilation never reads it.

## Commands

Load or replace a local knowledge database from a curated dataset:

```powershell
sekr dataset load --db .sekr/knowledge.sqlite --source data/coder_activation.json
```

Validate the loaded dataset:

```powershell
python -m sekr.cli dataset validate --db .sekr/knowledge.sqlite
```

Compile task context:

```powershell
python -m sekr.cli context compile --db .sekr/knowledge.sqlite --task "activate coder values" --budget 6
```

Evaluate the compiler against the deterministic normalized-token-overlap text baseline:

```powershell
python -B -m sekr.cli context evaluate --case coder-activation --budget 6
```

Evaluation output reports precision at K, critical recall, context size, false-positive rate and IDs, plus reproducibility. It never emits the oracle itself.

The candidate universe is **all artifacts in the validated dataset**, including artifacts retrieval does not return. Oracle expected IDs define the positives; all remaining dataset IDs are negatives. `falsePositiveRate = FP / (FP + TN)`, with 0.0 defined when there are no negative candidates. `candidateCount` reports the universe size; `trueNegativeCount` reports negatives not selected. Oracle IDs must belong to the dataset, and critical IDs must be expected IDs. Precision is selected positives / selected items; critical recall is selected critical IDs / all critical IDs; either is 0.0 for an empty denominator.

`contextSize` retains the selected artifact count. `contextSizeBytes` measures compact JSON serialized with sorted keys, `ensure_ascii=False`, separators `(',', ':')`, encoded as UTF-8 without a trailing newline. It measures the full compiler `ContextPackage` (including facts, sections, and explanations), versus the baseline's ordered array of selected artifact records (ID, artifact type, title, description, path, evidence, confidence). These payloads contain different information; the byte counts are not evidence that the compiler returns a smaller context. They exclude CLI pretty spacing and transport overhead.

With the curated fixture and budget 6, the compiler retrieves all four critical artifacts. The baseline misses the active-filter regression test and selects `repository.tenant_coder_repository`, which is outside the oracle's seven expected artifacts. Of the nine dataset artifacts, two are negatives, so the baseline FPR is 1 / (1 + 1) = 0.5.

```json
{
  "baseline": {
    "candidateCount": 9,
    "contextSize": 6,
    "contextSizeBytes": 1941,
    "criticalRecall": 0.75,
    "falsePositiveIds": ["repository.tenant_coder_repository"],
    "falsePositiveRate": 0.5,
    "precisionAtK": 0.8333333333333334,
    "trueNegativeCount": 1
  },
  "case": "coder-activation",
  "compiler": {
    "candidateCount": 9,
    "contextSize": 6,
    "contextSizeBytes": 6723,
    "criticalRecall": 1.0,
    "falsePositiveIds": [],
    "falsePositiveRate": 0.0,
    "precisionAtK": 1.0,
    "trueNegativeCount": 2
  },
  "reproducible": true,
  "warnings": []
}
```

Run the tests:

```powershell
pytest -q
```

## Scope boundaries

This PoC is local and deterministic. It supports only Tenant/Coder activation and deactivation. External services, additional domains, automatic oracle generation, live source ingestion, and deferred retrieval features remain deferred.
