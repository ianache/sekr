# SEKR P5 Knowledge Delta Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic Git-ref comparison that emits a JSON Knowledge Delta with file, Python symbol, impact, and commit changes.

**Architecture:** `git_delta.py` owns safe Git command execution and tree extraction. `delta.py` owns immutable data models, AST comparison, impact analysis, and canonical serialization. The CLI adds a thin `delta` command that maps structured errors and preserves stdout/stderr boundaries.

**Tech Stack:** Python 3.11+, standard library `subprocess`, `ast`, `json`, `dataclasses`, existing `StructuredError` and CLI conventions; pytest.

**Spec:** `docs/superpowers/specs/2026-09-10-sekr-p5-knowledge-delta-design.md`

## Global Constraints

- Compare only two Git refs in the current repository; do not modify SQLite, Neo4j, or MCP behavior.
- Never execute repository code or construct shell commands through interpolation.
- Use repository-relative POSIX paths and sorted arrays for deterministic output.
- Existing commands and P0/P1/P2/P4 tests must remain green.
- Errors use stable structured codes and do not leak secrets or full local paths.

---

### Task 1: Safe Git tree and commit reader

**Files:**
- Create: `src/sekr/git_delta.py`
- Test: `tests/test_git_delta.py`

**Interfaces:**
- Produces `GitDeltaSource(repo: Path)` with `validate_ref(ref: str)`, `changed_files(base: str, head: str)`, `read_tree(ref: str, path: str) -> bytes`, and `commits_between(base: str, head: str) -> list[dict[str, str]]`.
- All subprocess calls use `subprocess.run([...], cwd=repo, check=False, capture_output=True)` and map failures to `StructuredError`.

- [ ] **Step 1: Write failing tests** for a temporary Git repository containing added/modified/deleted files, commit metadata, invalid refs, non-repository paths, and a ref beginning with `-`.
- [ ] **Step 2: Run `pytest tests/test_git_delta.py -q`** and confirm the new API is absent or failing.
- [ ] **Step 3: Implement safe Git command wrappers** with explicit argument vectors, `--` separators, UTF-8 decoding, stable status parsing, and path normalization.
- [ ] **Step 4: Run `pytest tests/test_git_delta.py -q`** and verify all reader tests pass.
- [ ] **Step 5: Commit** with `git add src/sekr/git_delta.py tests/test_git_delta.py && git commit -m "feat: add safe git delta reader"`.

### Task 2: Delta models, AST symbols, and impact analysis

**Files:**
- Create: `src/sekr/delta.py`
- Test: `tests/test_delta.py`

**Interfaces:**
- Produces `KnowledgeDelta` with `to_dict()` and `build_delta(source: GitDeltaSource, base: str, head: str) -> KnowledgeDelta`.
- Symbol identity is `path:qualified_name`; qualified names include nested class/function names and symbol kind.

- [ ] **Step 1: Write failing tests** for canonical top-level keys, file add/modify/delete classification, AST symbol add/modify/delete, deterministic sorting, malformed Python handling, and impact edges for imports/calls.
- [ ] **Step 2: Run `pytest tests/test_delta.py -q`** and confirm failure.
- [ ] **Step 3: Implement frozen dataclasses and canonical `to_dict()`** with exact top-level keys and sorted arrays.
- [ ] **Step 4: Implement AST extraction** from `git show` bytes; represent parse failures as `DELTA_PARSE_ERROR` with repository paths only.
- [ ] **Step 5: Implement head-tree impact analysis** by collecting import targets and call names, linking only changed symbols and sorting `(source, target, relation, path)`.
- [ ] **Step 6: Run `pytest tests/test_delta.py -q`** and verify all model/analysis tests pass.
- [ ] **Step 7: Commit** with `git add src/sekr/delta.py tests/test_delta.py && git commit -m "feat: compute deterministic knowledge delta"`.

### Task 3: CLI command and JSON artifact output

**Files:**
- Modify: `src/sekr/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Adds `sekr delta --base REF --head REF [--output PATH]`.
- Uses `build_delta(GitDeltaSource(Path.cwd()), base, head)` and emits `KnowledgeDelta.to_dict()` through existing JSON serialization.

- [ ] **Step 1: Write failing CLI tests** for stdout JSON, `--output` file bytes, stderr-only success summary, invalid refs, and preservation of existing commands.
- [ ] **Step 2: Run the targeted CLI tests** and confirm failure.
- [ ] **Step 3: Add the parser branch and structured error mapping** without importing optional MCP/Neo4j dependencies eagerly.
- [ ] **Step 4: Implement output handling** so stdout is canonical JSON only when no output path is provided; output-path mode writes exact bytes and reports success on stderr.
- [ ] **Step 5: Run `pytest tests/test_cli.py -q`** and verify targeted behavior.
- [ ] **Step 6: Commit** with `git add src/sekr/cli.py tests/test_cli.py && git commit -m "feat: expose knowledge delta through cli"`.

### Task 4: Documentation, end-to-end verification, and regression coverage

**Files:**
- Modify: `README.md`
- Test: `tests/test_delta.py`, `tests/test_cli.py`

**Interfaces:**
- Documents the exact command, JSON fields, ref semantics, safety boundaries, and examples for stdout/file output.

- [ ] **Step 1: Add an end-to-end fixture test** that creates two commits, runs the CLI, and compares parsed output with the direct `build_delta()` result.
- [ ] **Step 2: Add a determinism test** that runs the same comparison twice and asserts identical bytes.
- [ ] **Step 3: Document installation-free usage, invalid-ref errors, and artifact examples** in README.
- [ ] **Step 4: Run `pytest -q` and `git diff --check`**; expected result is all tests passing and no whitespace errors.
- [ ] **Step 5: Commit** with `git add README.md tests/test_delta.py tests/test_cli.py && git commit -m "docs: verify sekr knowledge delta"`.

## Final verification

Run:

```powershell
pytest -q
git diff --check
python -m sekr.cli delta --base HEAD~1 --head HEAD
```

Expected: all tests pass, no diff whitespace errors, and the CLI emits one deterministic JSON object with no traceback.
