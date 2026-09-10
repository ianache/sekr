# SEKR P4 MCP Server and Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the deterministic SQLite Context Compiler through one MCP stdio tool and verify it across a real subprocess boundary with a reproducible harness.

**Architecture:** `mcp_server.py` uses the official Python MCP SDK's `FastMCP` to register `compile_context` and delegates directly to `ContextCompiler`. `mcp_harness.py` is a dependency-light newline-delimited JSON-RPC client used by tests to launch `sekr mcp serve`, initialize it, discover the tool, call it, and verify errors/determinism.

**Tech Stack:** Python 3.11+, existing `sekr` CLI/SQLite runtime, official Python MCP SDK (`mcp>=1,<2` optional extra), standard library subprocess/JSON, pytest.

**Spec:** `docs/superpowers/specs/2026-09-09-sekr-p4-mcp-harness-design.md`

## Global Constraints

- Use MCP `stdio`; stdout must contain only valid MCP JSON-RPC messages and diagnostics may go only to stderr.
- Expose exactly one tool named `compile_context`.
- Tool inputs are required `task: string`, `budget: integer >= 0`, and `db: string`; reject unknown properties.
- Delegate to `ContextCompiler(KnowledgeRepository(db)).compile(task, budget)`; do not duplicate ranking or validation logic.
- Successful `structuredContent` must equal `ContextPackage.to_dict()`.
- Never load or expose the evaluation oracle, passwords, or environment secrets.
- Keep the MCP dependency optional; existing non-MCP commands and tests must work without it.
- Preserve all existing P0/P1/P2 behavior and tests.

---

## File map

- Create `src/sekr/mcp_server.py`: MCP server registration, tool implementation, and SDK error bridge.
- Create `src/sekr/mcp_harness.py`: subprocess JSON-RPC client for operator/test use.
- Modify `src/sekr/cli.py`: `mcp serve --db PATH` command.
- Modify `pyproject.toml`: optional `mcp` dependency extra.
- Create `tests/test_mcp_server.py`: direct tool contract and error mapping tests.
- Create `tests/test_mcp_harness.py`: actual subprocess protocol tests.
- Modify `tests/test_cli.py`: MCP command and missing-SDK error tests.
- Modify `README.md`: installation and MCP usage.

### Task 1: Implement the MCP server tool

**Files:**
- Create: `src/sekr/mcp_server.py`
- Modify: `pyproject.toml`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `ContextCompiler`, `KnowledgeRepository`, `StructuredError`.
- Produces: `create_server(db_path: str | Path)`, `run_server(db_path: str | Path)`, and the registered `compile_context` tool.

- [ ] **Step 1: Add failing server contract tests**

```python
def test_compile_context_returns_canonical_package(seeded_db):
    server = create_server(seeded_db)
    result = invoke_registered_tool(server, "compile_context", {
        "task": "activate coder values", "budget": 6, "db": str(seeded_db)
    })
    assert result["structuredContent"]["task"] == "activate coder values"
    assert result["structuredContent"]["budget"] == 6
    assert len(result["structuredContent"]["items"]) == 6
    assert result["isError"] is False


def test_compile_context_rejects_invalid_budget(seeded_db):
    result = invoke_registered_tool(create_server(seeded_db), "compile_context", {
        "task": "activate coder values", "budget": -1, "db": str(seeded_db)
    })
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "INVALID_BUDGET"
```

- [ ] **Step 2: Run server tests and verify they fail**

Run: `pytest -q tests/test_mcp_server.py`

Expected: FAIL because `sekr.mcp_server` and its tool are not implemented.

- [ ] **Step 3: Add optional dependency and server implementation**

Add `mcp = ["mcp>=1,<2"]` to `project.optional-dependencies`. Import
`FastMCP` lazily inside `create_server`/`run_server`, so importing `sekr.cli`
without the extra remains possible. Register exactly one tool with an explicit
input schema for `task`, `budget`, and `db`. The tool must call the existing
Compiler and return a dictionary equal to `package.to_dict()`; the SDK will
serialize it as structured content. Catch `StructuredError` and return an
error result with `isError: True`, JSON text content, and
`{"error": error.to_dict()}` structured content. Do not include exception
strings that may contain paths or secrets beyond the existing structured
details. `run_server` must call `server.run(transport="stdio")` and never
print to stdout.

- [ ] **Step 4: Run server tests and verify they pass**

Run: `python -m pip install -e ".[test,mcp]"`; then
`pytest -q tests/test_mcp_server.py`.

Expected: all server contract tests PASS.

- [ ] **Step 5: Commit the server**

```powershell
git add src/sekr/mcp_server.py pyproject.toml tests/test_mcp_server.py
git commit -m "feat: expose sekr compiler as mcp tool"
```

### Task 2: Wire `sekr mcp serve` into the CLI

**Files:**
- Modify: `src/sekr/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_server(db_path)` from `sekr.mcp_server`.
- Produces: `sekr mcp serve --db PATH` and stable missing-dependency error behavior.

- [ ] **Step 1: Add failing CLI tests**

```python
def test_mcp_serve_requires_database_path(runner):
    result = runner("mcp", "serve")
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_INPUT"


def test_mcp_serve_missing_sdk_returns_structured_error(runner, seeded_db):
    result = runner("mcp", "serve", "--db", str(seeded_db), env={"SEKR_MCP_FORCE_MISSING": "1"})
    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "MCP_UNAVAILABLE"
```

- [ ] **Step 2: Run targeted CLI tests and verify they fail**

Run: `pytest -q tests/test_cli.py -k mcp`

Expected: FAIL because the parser has no `mcp` command.

- [ ] **Step 3: Implement parser and dispatch**

Register `mcp serve` with required `--db`. Dispatch to `run_server` without
calling `_emit`, because the server owns stdout for MCP messages. Convert a
missing SDK import into `StructuredError("MCP_UNAVAILABLE", "MCP server
dependency is not installed")`; preserve JSON output for startup failures
before the server starts. Do not add a test-only environment branch to
production code; if the missing-SDK test cannot safely simulate import failure,
replace it with a subprocess test using a Python environment without the
optional extra.

- [ ] **Step 4: Run CLI tests and verify they pass**

Run: `pytest -q tests/test_cli.py -k mcp`.

Expected: all MCP CLI tests PASS and existing CLI tests remain green.

- [ ] **Step 5: Commit CLI wiring**

```powershell
git add src/sekr/cli.py tests/test_cli.py
git commit -m "feat: add sekr mcp serve command"
```

### Task 3: Build the subprocess harness

**Files:**
- Create: `src/sekr/mcp_harness.py`
- Test: `tests/test_mcp_harness.py`

**Interfaces:**
- Consumes: `sekr mcp serve --db PATH` subprocess.
- Produces: `MCPHarness` with `initialize()`, `list_tools()`, `call_tool(name, arguments)`, and `close()`.

- [ ] **Step 1: Add failing harness tests**

```python
def test_harness_initializes_discovers_and_calls_compiler(seeded_db):
    with MCPHarness(seeded_db) as harness:
        info = harness.initialize()
        tools = harness.list_tools()
        first = harness.call_tool("compile_context", {
            "task": "activate coder values", "budget": 6, "db": str(seeded_db)
        })
        second = harness.call_tool("compile_context", {
            "task": "activate coder values", "budget": 6, "db": str(seeded_db)
        })
    assert info["serverInfo"]["name"] == "sekr"
    assert [tool["name"] for tool in tools] == ["compile_context"]
    assert first == second


def test_harness_reports_unknown_tool_without_server_crash(seeded_db):
    with MCPHarness(seeded_db) as harness:
        harness.initialize()
        error = harness.call_tool("unknown", {})
        assert error["isError"] is True
```

- [ ] **Step 2: Run harness tests and verify they fail**

Run: `pytest -q tests/test_mcp_harness.py`.

Expected: FAIL because `MCPHarness` does not exist.

- [ ] **Step 3: Implement newline-delimited JSON-RPC client**

Launch `[sys.executable, "-m", "sekr.cli", "mcp", "serve", "--db", str(db)]`
with `stdin`, `stdout`, and `stderr` pipes and `PYTHONPATH` inherited. Send
one JSON object per line with incrementing integer IDs; read one response line
per request with a timeout. `initialize()` sends protocol version
`2025-06-18`, then sends the `notifications/initialized` notification. Every
request must reject non-JSON or EOF with a descriptive `MCP_PROTOCOL_ERROR`.
`close()` closes stdin, waits briefly, and terminates only if needed; never
silently discards stderr. Keep the client free of the `mcp` SDK dependency.

- [ ] **Step 4: Run harness tests and verify they pass**

Run: `pytest -q tests/test_mcp_harness.py`.

Expected: all subprocess protocol tests PASS with no non-MCP stdout.

- [ ] **Step 5: Commit the harness**

```powershell
git add src/sekr/mcp_harness.py tests/test_mcp_harness.py
git commit -m "test: add sekr mcp subprocess harness"
```

### Task 4: Complete end-to-end verification and documentation

**Files:**
- Modify: `tests/test_mcp_server.py`
- Modify: `tests/test_mcp_harness.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: MCP server, CLI, and harness from Tasks 1–3.
- Produces: documented setup and end-to-end acceptance proof.

- [ ] **Step 1: Add end-to-end assertions**

Assert harness output equals direct `ContextCompiler` output after canonical
JSON serialization, repeated calls are byte-identical, invalid task/budget/
database inputs return the expected structured error codes, and oracle IDs do
not occur in any response text.

- [ ] **Step 2: Document MCP setup and operation**

Add `pip install -e ".[test,mcp]"`, the command
`sekr mcp serve --db .sekr/knowledge.sqlite`, a minimal MCP client/harness
example, the `compile_context` schema, stdio behavior, and the fact that the
server uses SQLite while Neo4j remains the P2 projection. State that the
optional MCP extra is required only for server execution.

- [ ] **Step 3: Run final verification**

Run: `pytest -q tests/test_mcp_server.py tests/test_mcp_harness.py tests/test_cli.py -k "mcp or harness"`.

Expected: all P4 tests PASS.

Run: `pytest -q`.

Expected: all existing P0/P1/P2 tests plus P4 tests PASS.

Run: `python -B -m sekr.cli mcp serve --db .sekr/knowledge.sqlite` only
through the harness or an MCP client; do not pipe arbitrary text to stdout.

- [ ] **Step 4: Commit final P4 verification and docs**

```powershell
git add tests/test_mcp_server.py tests/test_mcp_harness.py README.md
git commit -m "docs: verify sekr p4 mcp harness"
```

## Plan self-review

- Spec coverage: stdio, one tool, input schema, direct Compiler delegation,
  structured errors, no oracle/secrets, optional dependency, CLI entry point,
  subprocess harness, determinism, error paths, and documentation are covered
  by Tasks 1–4.
- Placeholder scan: no `TBD`, `TODO`, vague implementation steps, or
  unassigned files remain.
- Type consistency: Task 1 defines server functions, Task 2 consumes
  `run_server`, Task 3 launches the CLI and defines `MCPHarness`, and Task 4
  consumes the complete boundary.
- Scope check: HTTP, auth, Neo4j retrieval, resources, prompts, and sampling
  remain explicit non-goals.

