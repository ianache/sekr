# SEKR P5 Knowledge Delta Design

**Status:** Approved for planning

**Depends on:** P0/P1 deterministic compiler, P2 projection, and P4 MCP harness

## Goal

Produce a deterministic, reviewable JSON artifact describing the knowledge-relevant changes between two Git refs in the current repository.

## Scope

P5 compares `base` and `head` refs without modifying SQLite, Neo4j, or the MCP contract. It reports file-level changes for every path and symbol-level changes for Python files that can be parsed from the two trees. It also reports impact edges in the head tree for changed symbols that are imported or called by other Python symbols.

The primary interface is `sekr delta --base REF --head REF [--output PATH]`. Without `--output`, one canonical JSON document is written to stdout. With `--output`, the same bytes are written to the requested file and a short success summary is emitted to stderr, keeping stdout suitable for pipelines.

## Non-goals

- Executing code from either Git ref.
- Updating the knowledge database or Neo4j.
- Inferring semantic meaning from natural language or generating an evaluation oracle.
- Supporting non-Python symbol parsing beyond file-level changes.
- Exposing the delta as a new MCP tool in P5.

## Data contract

The top-level JSON object has exactly these keys:

```json
{
  "base": "REF",
  "head": "REF",
  "files": {"added": [], "modified": [], "deleted": []},
  "symbols": {"added": [], "modified": [], "deleted": []},
  "impact": [],
  "commits": []
}
```

All arrays are sorted deterministically. File entries are repository-relative POSIX paths. A symbol entry contains `path`, `qualified_name`, `kind`, and `signature`; a modified symbol also contains `change_type: "modified"` through its enclosing array semantics. An impact entry contains `source`, `target`, `relation`, and `path`, where `relation` is `imports` or `calls` and source/target are qualified symbols.

`commits` contains commits reachable from `head` and not from `base`, each represented by `id`, `author`, `subject`, and `timestamp`, sorted by `(timestamp, id)` ascending. Git metadata is read with commands that return structured fields and is never interpreted as executable code.

## Errors and safety

Invalid refs, non-Git directories, unreadable trees, malformed Python, and unwritable output paths become existing `StructuredError` JSON with stable codes (`DELTA_INVALID_REF`, `DELTA_NOT_REPOSITORY`, `DELTA_TREE_ERROR`, `DELTA_PARSE_ERROR`, or `DELTA_OUTPUT_ERROR`). Error messages must not include secrets or full local paths. Git commands use argument arrays, never shell interpolation. Ref names are passed as `--`-delimited arguments where applicable.

## Determinism and verification

The same repository state, refs, and command produces byte-for-byte identical JSON. Tests cover additions/modifications/deletions, Python symbol extraction, impact ordering, commit metadata, invalid refs, malformed Python, output writing, and stdout/stderr boundaries. Existing P0/P1/P2/P4 tests remain green.
