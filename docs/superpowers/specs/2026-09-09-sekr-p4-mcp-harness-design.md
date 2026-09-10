# SEKR P4 MCP Server and Harness Design

**Date:** 2026-09-09  
**Status:** Approved design  
**Scope:** MCP stdio server and reproducible subprocess harness  
**Depends on:** P1 Context Compiler and P2 validated dataset projection

## Objective

Expose the existing deterministic `ContextCompiler` as an MCP tool and prove
the integration with a subprocess harness. P4 provides an agent-facing
protocol boundary without changing ranking, budget, evidence, provenance, or
evaluation behavior.

The initial MCP backend is SQLite because it is the current compiler runtime.
Neo4j remains the P2 projection target; a Neo4j-backed compiler repository is
not part of P4.

## Scope and non-goals

Included:

- MCP server over `stdio` using the official Python MCP SDK.
- One tool named `compile_context`.
- Input validation for task text, budget, and database path.
- Structured compiler output and structured tool errors.
- CLI entry point `sekr mcp serve`.
- A subprocess harness that performs MCP initialization, tool discovery, tool
  calls, error calls, and deterministic repeated calls.
- Tests that never require a live Neo4j server or external service.

Excluded:

- Streamable HTTP transport, authentication, or remote deployment.
- Additional MCP resources, prompts, sampling, or notifications.
- Direct Neo4j retrieval or automatic backend selection.
- Oracle access or oracle IDs in any MCP response.

## Architecture

`src/sekr/mcp_server.py` owns MCP registration and translates tool calls to
`ContextCompiler(KnowledgeRepository(db)).compile(task, budget)`. It must not
duplicate ranking or validation logic. The SDK runs on `stdio`; all diagnostic
logging goes to `stderr` and `stdout` is reserved for MCP JSON-RPC messages.

`src/sekr/mcp_harness.py` is a small test/operator client using a subprocess
and newline-delimited JSON-RPC messages. It is intentionally independent from
the server SDK so it verifies the actual process boundary rather than a direct
Python function call.

`cli.py` adds `mcp serve --db PATH` and delegates to the server module. The
existing dataset/context/ingest commands remain unchanged.

## MCP contract

The server advertises one tool:

```json
{
  "name": "compile_context",
  "description": "Compile evidence-backed context for a bounded task",
  "inputSchema": {
    "type": "object",
    "properties": {
      "task": {"type": "string", "minLength": 1},
      "budget": {"type": "integer", "minimum": 0},
      "db": {"type": "string", "minLength": 1}
    },
    "required": ["task", "budget", "db"],
    "additionalProperties": false
  }
}
```

The successful `tools/call` result contains `structuredContent` equal to the
existing `ContextPackage.to_dict()` output and one JSON text content block for
clients that only consume unstructured content. It includes selected items,
facts, warnings, sections, evidence, confidence, and budget fields exactly as
the Compiler returns them.

`StructuredError` results use `isError: true`, a JSON text content block, and
`structuredContent: {"error": {"code", "message", "details"}}`. The oracle
is never loaded by the server, and neither passwords nor environment secrets
are included in responses.

## Lifecycle and CLI

The harness sends `initialize` with protocol version `2025-06-18`, receives a
server result with tool capability metadata, then sends the
`notifications/initialized` notification before `tools/list` and
`tools/call`. The server accepts one request per input line and terminates
cleanly on EOF.

The operator command is:

```text
sekr mcp serve --db .sekr/knowledge.sqlite
```

The `mcp` dependency is optional in the package metadata. Importing the normal
CLI and running non-MCP commands must work without it; `sekr mcp serve` returns
a structured installation error if it is missing.

## Verification

P4 is complete when:

- `tools/list` exposes exactly `compile_context` with the required schema.
- A harness `tools/call` returns the same canonical payload as direct
  `ContextCompiler.compile()` for the fixture.
- Repeating the same MCP call returns byte-for-byte equivalent JSON.
- Invalid task, negative budget, missing database, and unknown tool calls
  return structured errors without crashing the server process.
- Server stdout contains only JSON-RPC messages; logs, if any, go to stderr.
- The existing P0/P1/P2 suite remains green without an MCP installation.
- The harness test passes with the optional `mcp` dependency installed.

