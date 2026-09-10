# SEKR Context Compiler

SEKR is a local, deterministic proof of concept for compiling a bounded context package for the sole supported case: Tenant/Coder activation and deactivation. It reads a curated JSON dataset from SQLite and returns evidence-backed artifacts for a task. Its default compiler workflow uses no external services; Neo4j is an optional P2 projection target.

## Setup

Requires Python 3.11 or later. Create an environment, install the project with its test, MCP, and optional Neo4j dependencies, and load the curated fixture:

```powershell
python -m pip install -e ".[test,mcp,neo4j]"
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

## MCP server

Install the MCP extra when the server is the only optional feature you need:

```powershell
python -m pip install -e ".[mcp]"
```

Start the stdio server against a validated local database:

```powershell
sekr mcp serve --db .sekr/knowledge.sqlite
```

The server exposes one tool, `compile_context`, with `task` and `budget` arguments. A successful call returns the same JSON object as `ContextCompiler.compile(...).to_dict()` and is deterministic for the same database and arguments. Invalid task or budget inputs return an MCP tool error whose JSON text is `{"error": {"code": "...", ...}}`.

MCP traffic uses stdout exclusively: do not print banners, logs, or diagnostics there, because stdout is the JSON-RPC transport. The server emits no application diagnostics to stderr during normal operation. The CLI's pre-server failures (for example, a missing MCP installation) remain structured JSON on stdout with a non-zero exit code.

Run the real subprocess harness, which starts the server over stdio and compares it to the direct compiler:

```powershell
python -m pytest tests/test_mcp_harness.py -q
```

The harness verifies direct compiler equivalence, repeat-call determinism, structured invalid requests, and that compile output contains no evaluation-oracle fields.

## Neo4j projection

P2 projects the validated JSON fixture into Neo4j; it does not replace the SQLite compiler. Preview the projection without connecting to Neo4j:

```powershell
python -m sekr.cli ingest neo4j --source data/coder_activation.json --dry-run
```

For a live ingestion, provide the Neo4j connection through environment variables:

```powershell
$env:SEKR_NEO4J_URI = "bolt://localhost:7687"
$env:SEKR_NEO4J_USER = "neo4j"
$env:SEKR_NEO4J_PASSWORD = "your-password"
python -m sekr.cli ingest neo4j --source data/coder_activation.json
```

The graph uses `Dataset`, `Artifact`, `Fact`, and `TaskProfile` labels. Every relationship has the fixed type `RELATES_TO` and stores its semantic value in the `relation_type` property. Stable IDs and parameterized `MERGE` statements make repeated ingestion idempotent for the same projection.

The live Neo4j test runs twice against the configured endpoint and compares both summaries. It is skipped when `SEKR_NEO4J_URI`, `SEKR_NEO4J_USER`, or `SEKR_NEO4J_PASSWORD` is absent, so credentials and an external service are not required in CI.

## Scope boundaries

This PoC is local and deterministic. It supports only Tenant/Coder activation and deactivation. External source services, additional domains, automatic oracle generation, live source ingestion, and deferred retrieval features remain deferred.
