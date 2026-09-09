# SEKR-PoC Context Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local CLI Context Compiler that retrieves and ranks evidence-backed Tenant/Coder activation knowledge from a curated SQLite dataset and emits a bounded `ContextPackage`.

**Architecture:** A small Python package separates domain models, SQLite persistence, deterministic retrieval/ranking, compilation, CLI commands, and evaluation. The dataset is curated and versioned; no automatic repository ingestion, Neo4j, MCP, embeddings, or agent integration is included in v0.1.

**Tech Stack:** Python 3.11+, standard-library `sqlite3`/`argparse`/`json`, pytest, SQLite, JSON fixtures.

**Spec:** `docs/superpowers/specs/2026-09-07-sekr-poc-context-compiler-design.md`

## Global Constraints

- The sole evaluation case is the Tenant microservice change for activating/deactivating individual Coder values and excluding inactive values from active queries.
- The compiler is local and deterministic for the same dataset version, task, configuration, and budget.
- SQLite is the v0.1 storage layer; automatic repository ingestion and Neo4j are deferred.
- MCP, direct Codex integration, embeddings/vector search, Knowledge Delta, and Knowledge-as-Tests are deferred.
- Missing evidence must be represented as `UNKNOWN` or conflicted and must never be presented as verified.
- The curated dataset must exclude secrets and unauthorized source content.
- Invalid input and invalid datasets must produce structured errors and non-zero CLI exit codes.

## File map

- Create `pyproject.toml`: package metadata, Python requirement, pytest configuration, and console entry point.
- Create `src/sekr/__init__.py`: package version.
- Create `src/sekr/models.py`: typed domain models and JSON serialization.
- Create `src/sekr/errors.py`: structured domain/CLI errors.
- Create `src/sekr/db.py`: SQLite schema, connection, dataset loading, and repository queries.
- Create `src/sekr/compiler.py`: task interpretation, retrieval, explainable scoring, budget application, and package assembly.
- Create `src/sekr/cli.py`: `dataset validate`, `context compile`, and `context evaluate` commands.
- Create `data/coder_activation.json`: curated source dataset for the sole case.
- Create `data/oracle/coder_activation.json`: evaluation oracle excluded from compile input.
- Create `tests/test_models.py`, `tests/test_db.py`, `tests/test_compiler.py`, and `tests/test_cli.py`: focused unit and integration coverage.
- Create `README.md`: setup, commands, dataset format, and scope/deferred features.

---

### Task 1: Bootstrap package and domain contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/sekr/__init__.py`
- Create: `src/sekr/models.py`
- Create: `src/sekr/errors.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces `Artifact`, `Relation`, `KnowledgeFact`, `TaskProfile`, `DatasetMetadata`, `ContextItem`, `ContextPackage`, `EvaluationReport`, and `Confidence`/`ArtifactType` literals used by all later tasks.
- Produces `ContextPackage.to_dict()` and `EvaluationReport.to_dict()` for stable JSON output.

- [ ] **Step 1: Write failing model tests**

```python
def test_context_item_serializes_provenance_and_reason():
    item = ContextItem(
        id="symbol.coder_value_service",
        artifact_type="symbol",
        title="CoderValueService",
        relevance_score=0.92,
        confidence="APPROVED",
        evidence=["tenant/src/coder_value_service.py:10-42"],
        why_included=["matches_domain", "related_to_active_filter"],
    )
    assert item.to_dict()["confidence"] == "APPROVED"
    assert item.to_dict()["evidence"] == ["tenant/src/coder_value_service.py:10-42"]


def test_context_package_preserves_budget_and_truncation():
    package = ContextPackage(task="activate coder values", items=[], budget=3,
                             omitted_count=2, warnings=["budget_truncated"])
    assert package.to_dict()["budget"] == 3
    assert package.to_dict()["omittedCount"] == 2
```

- [ ] **Step 2: Run `pytest tests/test_models.py -q` and verify it fails because the package and models do not exist.**
- [ ] **Step 3: Implement frozen dataclasses, constrained string literals, camel-case JSON keys, and `StructuredError(code, message, details)` in `errors.py`.**
- [ ] **Step 4: Run `pytest tests/test_models.py -q` and verify it passes.**
- [ ] **Step 5: Commit with `git add pyproject.toml src/sekr tests/test_models.py && git commit -m "feat: define sekr compiler domain contracts"` when a Git repository is available.**

### Task 2: Implement SQLite schema and curated dataset loader

**Files:**
- Create: `src/sekr/db.py`
- Create: `data/coder_activation.json`
- Create: `tests/test_db.py`

**Interfaces:**
- Consumes the models from Task 1.
- Produces `init_db(path)`, `load_dataset(path, dataset_json)`, `validate_dataset(path)`, and `KnowledgeRepository.search_candidates(tokens)`.
- `search_candidates` returns `(Artifact, score_evidence)` candidates without applying the final context budget.

- [ ] **Step 1: Write failing database tests**

```python
def test_load_and_validate_curated_dataset(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    result = validate_dataset(db_path)
    assert result.valid is True
    assert result.artifact_count >= 8


def test_search_returns_service_query_and_test_candidates(tmp_path):
    db_path = seeded_db(tmp_path)
    candidates = KnowledgeRepository(db_path).search_candidates(
        ["coder", "activate", "active", "values"]
    )
    ids = {candidate.artifact.id for candidate in candidates}
    assert "symbol.coder_value_service" in ids
    assert "test.active_values_exclude_inactive" in ids
```

- [ ] **Step 2: Run `pytest tests/test_db.py -q` and verify it fails because the schema/repository is missing.**
- [ ] **Step 3: Implement SQLite tables `artifacts`, `relations`, `facts`, `task_profiles`, and `dataset_metadata`; enforce primary keys, foreign keys, valid artifact types, and required provenance.**
- [ ] **Step 4: Define the curated dataset with the target feature, API endpoint, domain/service symbols, repository/table, relevant tests, ADR/document, related facts, and explicit source evidence. Include at least one unrelated artifact for false-positive measurement.**
- [ ] **Step 5: Implement deterministic token normalization and candidate search over artifact text, task-profile terms, and one-hop/two-hop relations.**
- [ ] **Step 6: Run `pytest tests/test_db.py -q` and verify it passes.**
- [ ] **Step 7: Commit with `git add src/sekr/db.py data/coder_activation.json tests/test_db.py && git commit -m "feat: add curated sqlite knowledge dataset"` when a Git repository is available.**

### Task 3: Implement deterministic Context Compiler and budget handling

**Files:**
- Create: `src/sekr/compiler.py`
- Create: `tests/test_compiler.py`

**Interfaces:**
- Consumes `KnowledgeRepository.search_candidates(tokens)` from Task 2.
- Produces `ContextCompiler.compile(task: str, budget: int) -> ContextPackage`.
- Produces `ContextCompiler.score(candidate, task_tokens) -> RankedCandidate` with component scores for term match, relation proximity, artifact type, evidence quality, confidence, and freshness.

- [ ] **Step 1: Write failing compiler tests**

```python
def test_compile_prioritizes_active_filter_service_and_test(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "Allow activation and deactivation of Coder values and exclude inactive values",
        budget=6,
    )
    ids = [item.id for item in package.items]
    assert ids.index("symbol.coder_value_service") < ids.index("artifact.unrelated.billing")
    assert "test.active_values_exclude_inactive" in ids
    assert all(item.evidence for item in package.items)


def test_compile_reports_omitted_candidates_when_budget_is_small(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "activate coder values", budget=2
    )
    assert len(package.items) == 2
    assert package.omitted_count > 0
    assert "budget_truncated" in package.warnings
```

- [ ] **Step 2: Run `pytest tests/test_compiler.py -q` and verify it fails because `ContextCompiler` is missing.**
- [ ] **Step 3: Implement task tokenization for domain terms, verb normalization (`activate`/`deactivate`), and active/inactive concepts.**
- [ ] **Step 4: Implement the score as a fixed weighted sum, with weights declared as constants and returned in the explanation; sort ties by artifact ID for reproducibility.**
- [ ] **Step 5: Build `ContextPackage` sections from artifact types and facts, preserve evidence/confidence, and emit warnings for truncation, missing evidence, conflicts, and no candidates.**
- [ ] **Step 6: Run `pytest tests/test_compiler.py -q` and verify it passes.**
- [ ] **Step 7: Commit with `git add src/sekr/compiler.py tests/test_compiler.py && git commit -m "feat: compile bounded evidence-backed context"` when a Git repository is available.**

### Task 4: Add CLI commands and structured failures

**Files:**
- Create: `src/sekr/cli.py`
- Test: `tests/test_cli.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes `init_db`, `load_dataset`, `validate_dataset`, and `ContextCompiler`.
- Produces console entry point `sekr` with `dataset validate`, `context compile`, and `context evaluate`.
- `context compile --db PATH --task TEXT|--task-file PATH --budget N` writes JSON to stdout.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_context_compile_emits_json_and_zero_exit(seeded_db, runner):
    result = runner("context", "compile", "--db", str(seeded_db),
                    "--task", "activate coder values", "--budget", "5")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["task"] == "activate coder values"
    assert "items" in payload


def test_invalid_dataset_returns_structured_error(seeded_db, runner):
    remove_required_provenance(seeded_db)
    result = runner("dataset", "validate", "--db", str(seeded_db))
    assert result.returncode != 0
    assert json.loads(result.stdout)["error"]["code"] == "DATASET_INVALID"
```

- [ ] **Step 2: Run `pytest tests/test_cli.py -q` and verify it fails because the CLI entry point is missing.**
- [ ] **Step 3: Implement `argparse` subcommands, mutually exclusive `--task`/`--task-file`, positive integer budget validation, stdout JSON, and stderr-free machine-readable errors.**
- [ ] **Step 4: Wire `dataset validate` to return dataset counts and validation issues; wire `context compile` to return `ContextPackage`.**
- [ ] **Step 5: Add `data-dir`/oracle path options to `context evaluate` without exposing oracle contents in compile output.**
- [ ] **Step 6: Run `pytest tests/test_cli.py -q` and verify it passes.**
- [ ] **Step 7: Run `python -m sekr.cli context compile --help` and verify the documented options are present.**
- [ ] **Step 8: Commit with `git add pyproject.toml src/sekr/cli.py tests/test_cli.py && git commit -m "feat: expose sekr context compiler cli"` when a Git repository is available.**

### Task 5: Implement evaluation oracle, baseline, documentation, and full verification

**Files:**
- Create: `data/oracle/coder_activation.json`
- Modify: `src/sekr/cli.py`
- Modify: `src/sekr/compiler.py`
- Create: `tests/test_evaluation.py`
- Create: `README.md`

**Interfaces:**
- Oracle contains only expected artifact IDs and critical-artifact IDs; it is read by evaluation, never by compile.
- Produces `EvaluationReport` with precision@K, critical recall, context size, false positives, and reproducibility status.
- Baseline ranks artifacts by normalized textual token overlap using the same dataset.

- [ ] **Step 1: Write failing evaluation tests**

```python
def test_evaluation_compares_compiler_with_text_baseline(seeded_db, oracle_path):
    report = evaluate_case(seeded_db, oracle_path, case="coder-activation", budget=6)
    assert report.compiler.precision_at_k >= report.baseline.precision_at_k
    assert report.compiler.critical_recall >= 0.75
    assert report.compiler.context_size == 6


def test_repeated_compilation_is_reproducible(seeded_db):
    compiler = ContextCompiler(KnowledgeRepository(seeded_db))
    first = compiler.compile("activate coder values", budget=5).to_dict()
    second = compiler.compile("activate coder values", budget=5).to_dict()
    assert first == second
```

- [ ] **Step 2: Run `pytest tests/test_evaluation.py -q` and verify it fails because the oracle/evaluator is missing.**
- [ ] **Step 3: Add the hidden oracle with the human-identified relevant and critical artifact IDs for the Tenant/Coder activation case.**
- [ ] **Step 4: Implement baseline overlap scoring and evaluator metric calculations, including zero-denominator handling and false-positive IDs.**
- [ ] **Step 5: Ensure `context evaluate --case coder-activation` prints metrics only, never the oracle itself.**
- [ ] **Step 6: Write README setup, dataset format, commands, scope boundaries, and an example JSON output.**
- [ ] **Step 7: Run `pytest -q` and verify all tests pass.**
- [ ] **Step 8: Run `python -m sekr.cli dataset validate --db .sekr/knowledge.sqlite` after loading the fixture, then run `python -m sekr.cli context evaluate --case coder-activation`; verify validation succeeds and the report contains compiler/baseline metrics.**
- [ ] **Step 9: Commit with `git add data/oracle src/sekr tests/test_evaluation.py README.md && git commit -m "feat: add compiler evaluation and usage docs"` when a Git repository is available.**

## Plan self-review

- Spec coverage: architecture, curated SQLite model, deterministic ranking, budget, CLI, evaluation, errors, safety, and deferred integrations are covered by Tasks 1–5.
- Placeholder scan: no `TODO`, `TBD`, or unspecified implementation step is required; every task names files, interfaces, tests, commands, and expected outcomes.
- Type consistency: models are introduced in Task 1, repository contracts in Task 2, compiler contracts in Task 3, CLI wiring in Task 4, and evaluator contracts in Task 5.
- Scope check: the plan covers one subsystem—the Context Compiler—and excludes the independently deferred MCP, ingestion, Neo4j, Delta, and Knowledge-as-Tests work.
