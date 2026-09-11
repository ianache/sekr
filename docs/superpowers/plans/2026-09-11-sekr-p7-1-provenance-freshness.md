# SEKR P7.1 Provenance and Freshness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic provenance and freshness reporting for SEKR knowledge without mutating approved knowledge.

**Architecture:** Add a focused freshness module that consumes the existing canonical snapshot contract, resolves only safe local evidence paths, hashes bytes with SHA-256, and returns a deterministic report. Extend the CLI with `knowledge-freshness`; keep `knowledge-check` as the enforcement layer and add a GitLab report job using a fixed evaluation time.

**Tech Stack:** Python 3.11+, standard-library `json`, `hashlib`, `datetime`, `pathlib`, existing SEKR projection/checker/CLI, pytest, GitLab CI YAML.

**Spec:** `docs/superpowers/specs/2026-09-11-sekr-p7-1-provenance-freshness-design.md`

## Global Constraints

- `content_hash` is a SHA-256 hash of canonical UTF-8 source content used for verification.
- Evaluation time is supplied explicitly with `--as-of ISO-8601` and defaults to the current UTC clock only for interactive use.
- Hashing reads bytes only; it never imports or executes referenced code.
- Evidence paths are constrained to the permitted input/repository root.
- No step mutates the input, approved baseline, SQLite database, or Neo4j.
- Invalid input uses structured errors and exit code `1`.

---

### Task 1: Freshness domain model and deterministic evaluator

**Files:**
- Create: `src/sekr/freshness.py`
- Test: `tests/test_freshness.py`

**Interfaces:**
- Consumes: canonical snapshots with `nodes` and `relationships`; an explicit `datetime` evaluation instant; a `Path` evidence root.
- Produces: `FreshnessReport.to_dict()` with `as_of`, `valid`, `counts`, and sorted `records`; `evaluate_freshness(snapshot, as_of, root)`.

- [ ] **Step 1: Write failing tests for each freshness state**

```python
def test_evaluate_freshness_assigns_current_changed_stale_unverified_and_conflicted(tmp_path):
    (tmp_path / "current.md").write_text("same", encoding="utf-8")
    (tmp_path / "changed.md").write_text("new", encoding="utf-8")
    snapshot = {
        "nodes": [
            {"kind": "Fact", "key": "current", "properties": {
                "evidence": ["current.md"], "content_hash": "sha256:51037a4a37730f52c8732586a3d3b9f3f4f1f3e4f3b5f3f9c7f5c7c5c3f5f6f5"
            }},
            {"kind": "Fact", "key": "changed", "properties": {
                "evidence": ["changed.md"], "content_hash": "sha256:old"
            }},
            {"kind": "Fact", "key": "stale", "properties": {
                "valid_until": "2020-01-01T00:00:00Z"
            }},
            {"kind": "Fact", "key": "unverified", "properties": {}},
            {"kind": "Fact", "key": "conflicted", "properties": {
                "confidence": "CONFLICTED"
            }},
        ],
        "relationships": [],
    }

    report = evaluate_freshness(snapshot, datetime(2026, 9, 11, tzinfo=timezone.utc), tmp_path)

    assert report.to_dict()["counts"] == {
        "current": 1, "stale": 1, "changed": 1, "unverified": 1, "conflicted": 1
    }
```

Use a helper that computes the actual expected SHA-256 in the test rather than embedding a hand-calculated digest; the assertion must still verify the state is `current`.

- [ ] **Step 2: Run `pytest -q tests/test_freshness.py` and confirm it fails because `sekr.freshness` does not exist.**

- [ ] **Step 3: Implement the minimal evaluator**

Implement `FreshnessReport`, `evaluate_freshness`, safe evidence resolution, and `_record_state` with precedence `conflicted`, `unverified`, `changed`, `stale`, `current`. Read only files under `root`, ignore missing/unreadable evidence as `unverified`, and format hashes as `sha256:<lowercase hex>`.

- [ ] **Step 4: Add deterministic ordering and precedence tests**

```python
def test_freshness_uses_changed_before_stale_and_sorts_records(tmp_path):
    evidence = tmp_path / "evidence.md"
    evidence.write_text("current", encoding="utf-8")
    snapshot = {"nodes": [{"kind": "Fact", "key": "z", "properties": {
        "evidence": ["evidence.md"], "content_hash": "sha256:wrong",
        "valid_until": "2020-01-01T00:00:00Z"
    }}, {"kind": "Fact", "key": "a", "properties": {}}], "relationships": []}

    report = evaluate_freshness(snapshot, datetime(2026, 9, 11, tzinfo=timezone.utc), tmp_path)

    assert [record["key"] for record in report.records] == ["a", "z"]
    assert report.records[1]["state"] == "changed"
```

- [ ] **Step 5: Run `pytest -q tests/test_freshness.py` and verify all evaluator tests pass.**

- [ ] **Step 6: Commit**

```bash
git add tests/test_freshness.py src/sekr/freshness.py
git commit -m "feat: add deterministic knowledge freshness evaluator"
```

### Task 2: CLI command and structured input handling

**Files:**
- Modify: `src/sekr/cli.py: imports, _build_parser, _dispatch, output handling`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `evaluate_freshness`, existing `_read_knowledge`, and `--as-of ISO-8601`.
- Produces: `sekr knowledge-freshness --input PATH [--as-of ISO-8601] [--output PATH]`; exit `0` only when the report is valid.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_knowledge_freshness_emits_deterministic_report(tmp_path, runner):
    source = tmp_path / "source.md"
    source.write_text("evidence", encoding="utf-8")
    payload = {"nodes": [{"kind": "Fact", "key": "fact", "properties": {
        "evidence": ["source.md"], "content_hash": "sha256:wrong"
    }}], "relationships": []}
    current = tmp_path / "knowledge.json"
    current.write_text(json.dumps(payload), encoding="utf-8")

    result = runner("knowledge-freshness", "--input", str(current),
                    "--as-of", "2026-09-11T12:00:00Z")

    assert result.returncode == 1
    assert json.loads(result.stdout)["records"][0]["state"] == "changed"
```

- [ ] **Step 2: Run the focused test and verify it fails because the parser has no `knowledge-freshness` command.**

- [ ] **Step 3: Add parser, dispatch, ISO-8601 parsing, output writing, and exit handling**

Use `StructuredError("INVALID_PROVENANCE", ...)` for invalid `--as-of` values and `KNOWLEDGE_OUTPUT_ERROR` for unwritable output. Reuse the existing input loader so both datasets and canonical snapshots work. Do not include absolute evidence paths in the report.

- [ ] **Step 4: Add tests for snapshot/dataset input, output byte stability, invalid dates, and valid/invalid exit codes.**

- [ ] **Step 5: Run `pytest -q tests/test_freshness.py tests/test_cli.py -k "freshness"` and verify all focused tests pass.**

- [ ] **Step 6: Commit**

```bash
git add tests/test_cli.py src/sekr/cli.py
git commit -m "feat: expose knowledge freshness command"
```

### Task 3: Provenance validation and snapshot compatibility

**Files:**
- Modify: `src/sekr/knowledge_check.py: snapshot record validation`
- Modify: `src/sekr/ingest.py: projection property normalization if needed`
- Test: `tests/test_knowledge_check.py`, `tests/test_ingest.py`

**Interfaces:**
- Consumes: existing provenance fields (`source`, `evidence`, `source_version`, `content_hash`, `observed_at`, `valid_from`, `valid_until`).
- Produces: stable `INVALID_PROVENANCE` errors for malformed optional fields and snapshots that remain accepted by `knowledge-check`.

- [ ] **Step 1: Write failing tests for malformed provenance**

```python
def test_snapshot_rejects_invalid_provenance_hash_and_dates():
    with pytest.raises(StructuredError) as error:
        check_knowledge({"nodes": [{"kind": "Fact", "key": "f", "properties": {
            "content_hash": "md5:bad", "valid_until": "not-a-date"
        }}], "relationships": []}, {"nodes": [], "relationships": []})
    assert error.value.code == "INVALID_PROVENANCE"
```

- [ ] **Step 2: Run the focused test and verify the current checker accepts or misclassifies the malformed fields.**

- [ ] **Step 3: Implement shared provenance field validation**

Accept absent optional fields; when present require strings, `sha256:<64 lowercase hex>` for `content_hash`, and UTC-compatible ISO-8601 timestamps for date fields. Keep existing dataset validation behavior unchanged for records that do not use provenance.

- [ ] **Step 4: Run `pytest -q tests/test_knowledge_check.py tests/test_ingest.py` and verify compatibility.**

- [ ] **Step 5: Commit**

```bash
git add tests/test_knowledge_check.py tests/test_ingest.py src/sekr/knowledge_check.py src/sekr/ingest.py
git commit -m "fix: validate knowledge provenance fields"
```

### Task 4: GitLab freshness report job and documentation

**Files:**
- Modify: `.gitlab-ci.yml`
- Modify: `README.md`
- Test: `tests/test_gitlab_ci.py`

**Interfaces:**
- Consumes: `SEKR_KNOWLEDGE_INPUT`, `SEKR_KNOWLEDGE_AS_OF`, and the repository's freshness command.
- Produces: `knowledge-freshness` GitLab job and `.sekr/knowledge-freshness.json` artifact; no baseline mutation.

- [ ] **Step 1: Write failing YAML contract tests**

```python
def test_gitlab_pipeline_defines_fixed_time_freshness_report_job():
    pipeline = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    assert "knowledge-freshness:" in pipeline
    assert 'SEKR_KNOWLEDGE_AS_OF: "2026-09-11T00:00:00Z"' in pipeline
    assert "python -m sekr.cli knowledge-freshness" in pipeline
    assert "--as-of \"$SEKR_KNOWLEDGE_AS_OF\"" in pipeline
    assert "- .sekr/knowledge-freshness.json" in pipeline
```

- [ ] **Step 2: Run the focused YAML test and verify it fails because the job is absent.**

- [ ] **Step 3: Add the report job after `knowledge-check`**

Use the existing Python image and input variable, set a fixed default `SEKR_KNOWLEDGE_AS_OF`, retain `when: always`, and publish the JSON artifact for one week. Do not add commands that write `data/knowledge-baseline.json`.

- [ ] **Step 4: Document local and GitLab usage**

Document the fixed-time command, artifact path, and the distinction between freshness reporting and baseline approval.

- [ ] **Step 5: Run `pytest -q tests/test_gitlab_ci.py tests/test_freshness.py tests/test_cli.py -k "freshness or gitlab"`, then run `git diff --check`.**

- [ ] **Step 6: Commit**

```bash
git add .gitlab-ci.yml README.md tests/test_gitlab_ci.py
git commit -m "ci: publish knowledge freshness report"
```

### Task 5: Integrated verification and review

**Files:**
- Test: all existing test files

- [ ] **Step 1: Run the full suite with `pytest -q` and record the exact result.**

- [ ] **Step 2: Run the deterministic manual check twice**

```powershell
$env:PYTHONPATH = (Resolve-Path src)
python -m sekr.cli knowledge-freshness --input data/knowledge-baseline.json --as-of 2026-09-11T00:00:00Z
python -m sekr.cli knowledge-freshness --input data/knowledge-baseline.json --as-of 2026-09-11T00:00:00Z
```

Confirm byte-identical stdout for both runs and no writes to the baseline.

- [ ] **Step 3: Run `git diff --check` and inspect `git status --short` for unrelated artifacts.**

- [ ] **Step 4: Request independent code review using base `master` and the final P7.1 commit.**

- [ ] **Step 5: Commit any review fixes individually, rerun the full suite, and report the final test result before integration.**
