# SEKR P2 Ingestion and Neo4j Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic JSON-to-Neo4j ingestion vertical slice while preserving SQLite and the P1 Context Compiler as the reference runtime.

**Architecture:** `ingest.py` validates the existing JSON dataset and produces a driver-independent `GraphProjection`. `neo4j.py` persists that projection using parameterized Cypher, stable IDs, `MERGE`, and one transaction. `cli.py` exposes `sekr ingest neo4j` and `--dry-run` while preserving the existing JSON error contract.

**Tech Stack:** Python 3.11+, existing `sekr` CLI, dataclasses, JSON, SQLite validation, optional Neo4j Python driver, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-sekr-p2-ingestion-neo4j-design.md`

## Global Constraints

- Use `data/coder_activation.json` as the only P2 source fixture.
- Validate the complete dataset before opening a Neo4j session or issuing a write.
- Do not modify SQLite schema, `ContextCompiler`, evaluation behavior, or P0/P1 metrics.
- Use stable source IDs and `MERGE`; never use generated Neo4j IDs for identity.
- Use only parameterized Cypher; do not interpolate dataset values into labels or relationship types.
- Never print Neo4j passwords or include credentials in structured errors.
- Keep the Neo4j dependency optional so `pytest -q` and `--dry-run` work without a server.

---

## File map

- Create `src/sekr/ingest.py`: validated JSON loading and immutable graph projection records.
- Create `src/sekr/neo4j.py`: Neo4j driver boundary, Cypher writes, transaction/error mapping.
- Modify `src/sekr/cli.py`: parser and dispatch for `ingest neo4j`.
- Modify `pyproject.toml`: optional `neo4j` dependency extra.
- Create `tests/test_ingest.py`: projection, counts, determinism, and pre-write validation tests.
- Create `tests/test_neo4j.py`: fake-driver adapter and optional live integration test.
- Modify `tests/test_cli.py`: dry-run and CLI error-contract tests.
- Modify `README.md`: setup, command, graph contract, and live-test instructions.

### Task 1: Build the driver-independent graph projection

**Files:**
- Create: `src/sekr/ingest.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: local JSON dataset path and existing validation behavior from `sekr.db`.
- Produces: `GraphProjection`, `GraphNode`, `GraphRelationship`, `IngestSummary`, and `build_graph_projection(path)` for Tasks 2 and 3.

- [ ] **Step 1: Write failing projection tests**

```python
def test_projection_has_expected_fixture_counts():
    projection = build_graph_projection(Path("data/coder_activation.json"))
    assert projection.dataset.properties["version"] == "0.1.0"
    assert {node.kind for node in projection.nodes} == {"Artifact", "Fact", "TaskProfile"}
    assert len(projection.nodes) == 12
    assert len(projection.relationships) == 25


def test_projection_is_deterministic():
    first = build_graph_projection(Path("data/coder_activation.json"))
    second = build_graph_projection(Path("data/coder_activation.json"))
    assert first == second


def test_invalid_relation_reference_fails_before_projection(tmp_path):
    data = json.loads(Path("data/coder_activation.json").read_text(encoding="utf-8"))
    data["relations"][0]["target_id"] = "artifact.missing"
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(StructuredError) as error:
        build_graph_projection(source)
    assert error.value.code == "INVALID_REFERENCE"
```

- [ ] **Step 2: Run projection tests and verify they fail**

Run: `pytest -q tests/test_ingest.py`

Expected: FAIL because `sekr.ingest` and `build_graph_projection` do not exist.

- [ ] **Step 3: Implement immutable projection records and conversion**

Implement `GraphNode(kind: str, key: str, properties: Mapping[str, object])`,
`GraphRelationship(key: str, source_kind: str, source_key: str,
target_kind: str, target_key: str, properties: Mapping[str, object])`, and
`GraphProjection(dataset: GraphNode, nodes: tuple[GraphNode, ...],
relationships: tuple[GraphRelationship, ...])` as frozen dataclasses.

Implement `build_graph_projection(path)` by reading UTF-8 JSON, calling the
same raw dataset checks used by `load_dataset` through a small public helper
`validate_dataset_json(data)` in `sekr.db`, then sorting artifacts, facts,
profiles, and relations by ID. Create 12 non-dataset nodes from the fixture:
9 artifacts, 2 facts, and 1 profile, plus the dataset node. Create 25
relationships: 9 dataset-to-artifact, 2 artifact-to-fact, 1 dataset-to-
profile, 7 profile-to-artifact, and 6 artifact-to-artifact source relations.
Copy all source properties,
including empty optional values as `None` where Neo4j cannot store an empty
value, and preserve `expected_artifacts` as a profile property for dry-run
and projection consumers.

- [ ] **Step 4: Run projection tests and verify they pass**

Run: `pytest -q tests/test_ingest.py`

Expected: all projection tests PASS.

- [ ] **Step 5: Commit the projection**

```powershell
git add src/sekr/ingest.py src/sekr/db.py tests/test_ingest.py
git commit -m "feat: add deterministic sekr graph projection"
```

### Task 2: Add the Neo4j persistence adapter

**Files:**
- Create: `src/sekr/neo4j.py`
- Modify: `pyproject.toml`
- Test: `tests/test_neo4j.py`

**Interfaces:**
- Consumes: `GraphProjection` from `sekr.ingest`.
- Produces: `write_projection(projection, uri, user, password)` and
  `IngestSummary` with `nodes_written` and `relationships_written`.

- [ ] **Step 1: Write failing fake-driver tests**

```python
def test_write_projection_uses_stable_merge_keys_and_returns_counts(monkeypatch):
    driver = RecordingDriver()
    monkeypatch.setattr("sekr.neo4j.GraphDatabase.driver", lambda *args, **kwargs: driver)
    summary = write_projection(build_graph_projection(DATASET), uri="bolt://db", user="neo4j", password="secret")
    assert summary.nodes_written == 13
    assert summary.relationships_written == 25
    assert all("MERGE" in query for query, _ in driver.session.queries)
    assert all("secret" not in query for query, _ in driver.session.queries)
    assert driver.session.committed is True


def test_write_projection_maps_driver_failure_to_structured_error(monkeypatch):
    monkeypatch.setattr("sekr.neo4j.GraphDatabase.driver", failing_driver)
    with pytest.raises(StructuredError) as error:
        write_projection(build_graph_projection(DATASET), uri="bolt://db", user="neo4j", password="secret")
    assert error.value.code == "NEO4J_CONNECTION_ERROR"
```

- [ ] **Step 2: Run adapter tests and verify they fail**

Run: `pytest -q tests/test_neo4j.py`

Expected: FAIL because the adapter and optional driver boundary do not exist.

- [ ] **Step 3: Add the optional dependency and adapter implementation**

Add `[project.optional-dependencies] neo4j = ["neo4j>=5,<7"]` while keeping
the existing `test` extra unchanged. Import `GraphDatabase` lazily inside the
write function and raise `NEO4J_CONNECTION_ERROR` with an installation hint
if the extra is not installed.

Implement `write_projection` with `GraphDatabase.driver(uri, auth=(user,
password))`, a single session transaction, and one parameterized statement
for each node and relationship. Node statements must use
`MERGE (n:<fixed-label> {id: $id}) SET n += $properties`; relationship
statements must match endpoint labels by stable ID and use
`MERGE (source)-[r:RELATES_TO {id: $id}]->(target) SET r += $properties`.
Use fixed labels from the projection (`Dataset`, `Artifact`, `Fact`,
`TaskProfile`) and store `relation_type` in relationship properties. Close
the driver in `finally`; rollback on transaction errors and map connection
errors to `NEO4J_CONNECTION_ERROR`, write errors to `NEO4J_WRITE_ERROR`.

- [ ] **Step 4: Run adapter tests and verify they pass**

Run: `pytest -q tests/test_neo4j.py`

Expected: fake-driver tests PASS, including stable keys and sanitized output.

- [ ] **Step 5: Commit the adapter**

```powershell
git add src/sekr/neo4j.py pyproject.toml tests/test_neo4j.py
git commit -m "feat: persist sekr projection in neo4j"
```

### Task 3: Expose ingestion and dry-run through the CLI

**Files:**
- Modify: `src/sekr/cli.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `build_graph_projection` and `write_projection`.
- Produces: `sekr ingest neo4j --source PATH [--uri URI --user USER --password PASSWORD] [--dry-run]`.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_ingest_dry_run_emits_projection_summary(runner):
    result = runner("ingest", "neo4j", "--source", "data/coder_activation.json", "--dry-run")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {
        "dry_run": True,
        "dataset_version": "0.1.0",
        "nodes": 13,
        "relationships": 25,
        "validated": True,
    }


def test_ingest_rejects_missing_connection_options(runner):
    result = runner("ingest", "neo4j", "--source", "data/coder_activation.json")
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_INPUT"
```

- [ ] **Step 2: Run CLI tests and verify they fail**

Run: `pytest -q tests/test_cli.py -k ingest`

Expected: FAIL because the `ingest` command is not registered.

- [ ] **Step 3: Implement parser and dispatch**

Add an `ingest` subparser with a required `neo4j` child parser. Require
`--source`; accept `--uri`, `--user`, and `--password` only for non-dry runs,
with defaults from `SEKR_NEO4J_URI`, `SEKR_NEO4J_USER`, and
`SEKR_NEO4J_PASSWORD`. Reject a non-dry run if any connection option is
missing. For `--dry-run`, build the projection and return exactly the summary
shape asserted above. For a live run, call `write_projection` and return
`dry_run: false`, dataset version, and the two write counts. Keep `_emit` and
`main` unchanged except for importing the new modules and allowing the new
structured error codes.

- [ ] **Step 4: Run CLI tests and verify they pass**

Run: `pytest -q tests/test_cli.py -k ingest`

Expected: all ingestion CLI tests PASS and passwords do not appear in stdout.

- [ ] **Step 5: Commit the CLI**

```powershell
git add src/sekr/cli.py tests/test_cli.py
git commit -m "feat: add sekr neo4j ingestion cli"
```

### Task 4: Add optional live verification and document P2 usage

**Files:**
- Modify: `tests/test_neo4j.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: CLI and adapter commands from Tasks 2 and 3.
- Produces: reproducible operator instructions and an environment-gated live integration test.

- [ ] **Step 1: Add the skipped-by-default live test**

```python
@pytest.mark.skipif(
    not all(os.getenv(name) for name in ("SEKR_NEO4J_URI", "SEKR_NEO4J_USER", "SEKR_NEO4J_PASSWORD")),
    reason="Neo4j integration credentials are not configured",
)
def test_live_neo4j_ingestion_is_idempotent():
    first = write_projection(build_graph_projection(DATASET), uri=os.environ["SEKR_NEO4J_URI"], user=os.environ["SEKR_NEO4J_USER"], password=os.environ["SEKR_NEO4J_PASSWORD"])
    second = write_projection(build_graph_projection(DATASET), uri=os.environ["SEKR_NEO4J_URI"], user=os.environ["SEKR_NEO4J_USER"], password=os.environ["SEKR_NEO4J_PASSWORD"])
    assert first == second
```

- [ ] **Step 2: Update README with the P2 command and contract**

Document installation with `pip install -e ".[test,neo4j]"`, the dry-run
command, the live command using environment variables, the labels and
relationship properties, and the fact that P2 projects the validated JSON
fixture without changing the SQLite compiler. Explicitly state that the live
test is skipped when credentials are absent.

- [ ] **Step 3: Run targeted and full verification**

Run: `pytest -q tests/test_ingest.py tests/test_neo4j.py tests/test_cli.py -k "ingest or neo4j"`

Expected: fake-driver and CLI tests pass; live test is skipped without credentials.

Run: `pytest -q`

Expected: the full P0/P1/P2 suite passes with no failures.

Run: `python -m sekr.cli ingest neo4j --source data/coder_activation.json --dry-run`

Expected: JSON reports version `0.1.0`, 13 nodes, 25 relationships, and
`validated: true` without requiring Neo4j.

- [ ] **Step 4: Commit the verified P2 vertical slice**

```powershell
git add tests/test_neo4j.py README.md
git commit -m "docs: verify and document sekr p2 ingestion"
```

## Plan self-review

- Spec coverage: source validation, canonical projection, graph labels,
  stable MERGE identity, provenance, dry-run, structured errors, optional live
  test, and preservation of P1 are covered by Tasks 1–4.
- Placeholder scan: no `TBD`, `TODO`, vague implementation step, or deferred
  code requirement is present.
- Type consistency: Task 1 defines `GraphProjection`, Task 2 consumes it and
  defines `IngestSummary`, and Tasks 3–4 consume both interfaces.
- Scope check: this plan contains one vertical slice; repository scanners,
  incremental synchronization, MCP, and Knowledge Delta remain explicit
  non-goals.
