"""Machine-readable command-line interface for the SEKR Context Compiler."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from sekr.compiler import ContextCompiler, evaluate_case
from sekr.db import KnowledgeRepository, load_dataset, validate_dataset
from sekr.delta import build_delta
from sekr.errors import StructuredError
from sekr.freshness import evaluate_freshness
from sekr.git_delta import GitDeltaSource
from sekr.ingest import build_graph_projection
from sekr.knowledge_check import (
    build_knowledge_snapshot,
    check_knowledge,
    evaluate_knowledge_policy,
    projection_to_snapshot,
)
from sekr.neo4j import write_projection


class _Parser(argparse.ArgumentParser):
    """Convert argparse failures into the CLI's JSON error contract."""

    def error(self, message: str) -> None:
        code = "INVALID_BUDGET" if "--budget" in message else "INVALID_INPUT"
        raise StructuredError(code, message)


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("budget must be a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("budget must be a positive integer")
    return parsed


def _build_parser() -> _Parser:
    parser = _Parser(prog="sekr", description="Local deterministic SEKR Context Compiler")
    commands = parser.add_subparsers(dest="command", required=True)

    dataset = commands.add_parser("dataset")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    validate = dataset_commands.add_parser("validate")
    validate.add_argument("--db", required=True, metavar="PATH")
    load = dataset_commands.add_parser("load")
    load.add_argument("--db", required=True, metavar="PATH")
    load.add_argument("--source", required=True, metavar="PATH")

    context = commands.add_parser("context")
    context_commands = context.add_subparsers(dest="context_command", required=True)
    compile_command = context_commands.add_parser("compile")
    compile_command.add_argument("--db", required=True, metavar="PATH")
    task_source = compile_command.add_mutually_exclusive_group(required=True)
    task_source.add_argument("--task", metavar="TEXT")
    task_source.add_argument("--task-file", metavar="PATH")
    compile_command.add_argument("--budget", required=True, type=_positive_integer, metavar="N")

    evaluate = context_commands.add_parser("evaluate")
    evaluate.add_argument("--db", default=".sekr/knowledge.sqlite", metavar="PATH")
    evaluate.add_argument("--case", required=True)
    evaluate.add_argument("--budget", default=6, type=_positive_integer, metavar="N")
    evaluate.add_argument("--data-dir", default="data", metavar="PATH")
    evaluate.add_argument("--oracle-path", metavar="PATH")

    ingest = commands.add_parser("ingest")
    ingest_commands = ingest.add_subparsers(dest="ingest_command", required=True)
    neo4j = ingest_commands.add_parser("neo4j")
    neo4j.add_argument("--source", required=True, metavar="PATH")
    neo4j.add_argument("--uri", metavar="URI")
    neo4j.add_argument("--user", metavar="USER")
    neo4j.add_argument("--password", metavar="PASSWORD")
    neo4j.add_argument("--dry-run", action="store_true")

    mcp = commands.add_parser("mcp")
    mcp_commands = mcp.add_subparsers(dest="mcp_command", required=True)
    serve = mcp_commands.add_parser("serve")
    serve.add_argument("--db", required=True, metavar="PATH")

    delta = commands.add_parser("delta")
    delta.add_argument("--base", required=True, metavar="REF")
    delta.add_argument("--head", required=True, metavar="REF")
    delta.add_argument("--output", metavar="PATH")

    knowledge_check = commands.add_parser("knowledge-check")
    knowledge_check.add_argument("--input", required=True, metavar="PATH")
    knowledge_check.add_argument("--baseline", required=True, metavar="PATH")
    knowledge_check.add_argument("--policy", metavar="PATH")
    knowledge_check.add_argument("--output", metavar="PATH")

    knowledge_snapshot = commands.add_parser("knowledge-snapshot")
    knowledge_snapshot.add_argument("--input", required=True, metavar="PATH")
    knowledge_snapshot.add_argument("--output", required=True, metavar="PATH")

    knowledge_freshness = commands.add_parser("knowledge-freshness")
    knowledge_freshness.add_argument("--input", required=True, metavar="PATH")
    knowledge_freshness.add_argument("--as-of", metavar="ISO-8601")
    knowledge_freshness.add_argument("--output", metavar="PATH")

    return parser


def _validation_payload(path: str | Path) -> dict[str, object]:
    validation = validate_dataset(path)
    return {
        "valid": validation.valid,
        "counts": {"artifacts": validation.artifact_count},
        "issues": [error.to_dict() for error in validation.errors],
    }


def _require_valid_dataset(path: str | Path) -> None:
    payload = _validation_payload(path)
    if not payload["valid"]:
        raise StructuredError(
            "DATASET_INVALID",
            "Dataset validation failed",
            {"issues": payload["issues"], "counts": payload["counts"]},
        )


def _read_task(task: str | None, task_file: str | None) -> str:
    if task is not None:
        return task
    try:
        return Path(task_file or "").read_text(encoding="utf-8")
    except OSError as error:
        raise StructuredError("INVALID_TASK", "Task file could not be read", {"error": str(error)}) from error


def _connection_value(value: str | None, environment_name: str) -> str | None:
    return value or os.environ.get(environment_name)


def _serve_mcp(db_path: str) -> None:
    try:
        from sekr.mcp_server import run_server

        run_server(db_path)
    except ModuleNotFoundError as error:
        if error.name != "mcp":
            raise
        raise StructuredError(
            "MCP_UNAVAILABLE",
            "MCP support is not installed",
            {"hint": "Install it with: pip install mcp"},
        ) from None


def _dispatch(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "delta":
        return build_delta(
            GitDeltaSource(Path.cwd()), arguments.base, arguments.head
        ).to_dict()

    if arguments.command == "knowledge-check":
        current = _read_knowledge(arguments.input)
        baseline = _read_knowledge(arguments.baseline)
        report = check_knowledge(current, baseline)
        payload = report.to_dict()
        payload["policy"] = evaluate_knowledge_policy(
            report, _read_policy(arguments.policy) if arguments.policy else None
        )
        return payload

    if arguments.command == "knowledge-snapshot":
        return build_knowledge_snapshot(arguments.input)

    if arguments.command == "knowledge-freshness":
        return evaluate_freshness(
            _read_knowledge(arguments.input), _parse_as_of(arguments.as_of), Path(arguments.input).parent
        ).to_dict()

    if arguments.command == "dataset":
        if arguments.dataset_command == "load":
            load_dataset(arguments.db, arguments.source)
            validation = _validation_payload(arguments.db)
            return {
                "loaded": True,
                "counts": validation["counts"],
                "db": str(arguments.db),
                "source": str(arguments.source),
            }
        payload = _validation_payload(arguments.db)
        if not payload["valid"]:
            raise StructuredError("DATASET_INVALID", "Dataset validation failed", payload)
        return payload

    if arguments.command == "ingest":
        projection = build_graph_projection(arguments.source)
        if arguments.dry_run:
            return {
                "dry_run": True,
                "dataset_version": projection.dataset.key,
                "nodes": 1 + len(projection.nodes),
                "relationships": len(projection.relationships),
                "validated": True,
            }

        uri = _connection_value(arguments.uri, "SEKR_NEO4J_URI")
        user = _connection_value(arguments.user, "SEKR_NEO4J_USER")
        password = _connection_value(arguments.password, "SEKR_NEO4J_PASSWORD")
        if not all((uri, user, password)):
            raise StructuredError(
                "INVALID_INPUT",
                "Neo4j URI, user, and password are required for live ingestion",
            )
        summary = write_projection(projection, uri=uri, user=user, password=password)
        return {
            "dry_run": False,
            "dataset_version": projection.dataset.key,
            "nodes_written": summary.nodes_written,
            "relationships_written": summary.relationships_written,
        }

    if arguments.context_command == "compile":
        _require_valid_dataset(arguments.db)
        task = _read_task(arguments.task, arguments.task_file)
        return ContextCompiler(KnowledgeRepository(arguments.db)).compile(task, arguments.budget).to_dict()

    if arguments.context_command == "evaluate":
        _require_valid_dataset(arguments.db)
        oracle_path = arguments.oracle_path or str(
            Path(arguments.data_dir) / "oracle" / f"{arguments.case.replace('-', '_')}.json"
        )
        return evaluate_case(
            arguments.db, oracle_path, case=arguments.case, budget=arguments.budget
        ).to_dict()

    raise StructuredError(
        "EVALUATION_UNAVAILABLE",
        "Context evaluation is not available until the evaluation oracle is installed",
        {"case": arguments.case},
    )


def _serialize(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def _emit(payload: dict[str, object]) -> None:
    os.sys.stdout.buffer.write(_serialize(payload))


def _write_delta_output(path: str, payload: dict[str, object]) -> None:
    try:
        Path(path).write_bytes(_serialize(payload))
    except OSError as error:
        raise StructuredError("DELTA_OUTPUT_ERROR", "Knowledge delta could not be written") from error
    print(f"Wrote knowledge delta to {path}", file=os.sys.stderr)


def _read_knowledge(path: str | Path) -> dict[str, object]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StructuredError(
            "INVALID_KNOWLEDGE", "Knowledge JSON could not be read", {"error": str(error)}
        ) from error
    if isinstance(data, dict) and "nodes" in data and "relationships" in data:
        return data
    if isinstance(data, dict):
        return projection_to_snapshot(build_graph_projection(path))
    raise StructuredError("INVALID_KNOWLEDGE", "Knowledge JSON must be an object")


def _read_policy(path: str | Path) -> dict[str, object]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StructuredError(
            "INVALID_POLICY", "Knowledge policy JSON could not be read", {"error": str(error)}
        ) from error
    if not isinstance(data, dict):
        raise StructuredError("INVALID_POLICY", "Knowledge policy JSON must be an object")
    return data


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise StructuredError("INVALID_PROVENANCE", "As-of timestamp must be ISO-8601 UTC") from error
    if parsed.tzinfo is None:
        raise StructuredError("INVALID_PROVENANCE", "As-of timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _write_knowledge_output(path: str, payload: dict[str, object]) -> None:
    try:
        Path(path).write_bytes(_serialize(payload))
    except OSError as error:
        raise StructuredError(
            "KNOWLEDGE_OUTPUT_ERROR", "Knowledge check report could not be written"
        ) from error
    print(f"Wrote knowledge check report to {path}", file=os.sys.stderr)


def _write_snapshot_output(path: str, payload: dict[str, object]) -> None:
    try:
        Path(path).write_bytes(_serialize(payload))
    except OSError as error:
        raise StructuredError(
            "KNOWLEDGE_OUTPUT_ERROR", "Knowledge snapshot could not be written"
        ) from error
    print(f"Wrote knowledge snapshot to {path}", file=os.sys.stderr)


def _write_freshness_output(path: str, payload: dict[str, object]) -> None:
    try:
        Path(path).write_bytes(_serialize(payload))
    except OSError as error:
        raise StructuredError(
            "KNOWLEDGE_OUTPUT_ERROR", "Knowledge freshness report could not be written"
        ) from error
    print(f"Wrote knowledge freshness report to {path}", file=os.sys.stderr)


def _ensure_freshness_output_is_safe(output: str | Path, input_path: str | Path) -> None:
    output_path = Path(output).resolve()
    protected = {Path(input_path).resolve(), (Path.cwd() / "data" / "knowledge-baseline.json").resolve()}
    configured_baseline = os.environ.get("SEKR_KNOWLEDGE_BASELINE")
    if configured_baseline:
        protected.add(Path(configured_baseline).resolve())
    if output_path in protected:
        raise StructuredError("KNOWLEDGE_OUTPUT_ERROR", "Knowledge freshness output must not overwrite an input or approved baseline")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        arguments = parser.parse_args(argv)
        if arguments.command == "mcp":
            _serve_mcp(arguments.db)
            return 0
        payload = _dispatch(arguments)
        if arguments.command == "delta" and arguments.output is not None:
            _write_delta_output(arguments.output, payload)
        elif arguments.command == "knowledge-check" and arguments.output is not None:
            _write_knowledge_output(arguments.output, payload)
        elif arguments.command == "knowledge-snapshot":
            _write_snapshot_output(arguments.output, payload)
        elif arguments.command == "knowledge-freshness" and arguments.output is not None:
            _ensure_freshness_output_is_safe(arguments.output, arguments.input)
            _write_freshness_output(arguments.output, payload)
        else:
            _emit(payload)
        if arguments.command == "knowledge-check":
            return 0 if payload["policy"]["allowed"] else 1
        if arguments.command == "knowledge-freshness":
            return 0 if payload["valid"] else 1
        return 0
    except StructuredError as error:
        _emit({"error": error.to_dict()})
        return 1
    except (OSError, ValueError) as error:
        _emit({"error": StructuredError("INVALID_INPUT", str(error)).to_dict()})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
