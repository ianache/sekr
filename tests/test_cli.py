import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
from unittest.mock import Mock

import pytest

from sekr.db import init_db, load_dataset
from sekr.neo4j import IngestSummary


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


@pytest.fixture
def runner():
    def run(*args, env=None, cwd=None):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path("src").resolve())
        if env:
            for name, value in env.items():
                if value is None:
                    environment.pop(name, None)
                else:
                    environment[name] = value
        return subprocess.run(
            [sys.executable, "-m", "sekr.cli", *args],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            cwd=cwd,
        )

    return run


@pytest.fixture
def binary_runner():
    def run(*args):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(Path("src").resolve())
        return subprocess.run(
            [sys.executable, "-m", "sekr.cli", *args],
            capture_output=True,
            check=False,
            env=environment,
        )

    return run


def run_with_patched_neo4j_adapter(*args, env):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path("src").resolve())
    environment.update(env)
    script = textwrap.dedent(
        """
        from unittest.mock import patch

        from sekr.cli import main
        from sekr.neo4j import IngestSummary

        with patch(
            "sekr.cli.write_projection",
            return_value=IngestSummary(nodes_written=13, relationships_written=25),
        ):
            raise SystemExit(main())
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script, *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def run_with_patched_mcp_server(*args, marker_path, sdk_unavailable=False):
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path("src").resolve())
    script = textwrap.dedent(
        """
        import sys
        from pathlib import Path
        from types import ModuleType

        server = ModuleType("sekr.mcp_server")

        def run_server(db_path):
            if sys.argv[2] == "unavailable":
                raise ModuleNotFoundError("No module named 'mcp'", name="mcp")
            Path(sys.argv[1]).write_text(str(db_path), encoding="utf-8")
            print('{"jsonrpc":"2.0","method":"ready"}')

        server.run_server = run_server
        sys.modules["sekr.mcp_server"] = server

        from sekr.cli import main

        raise SystemExit(main(sys.argv[3:]))
        """
    )
    mode = "unavailable" if sdk_unavailable else "available"
    return subprocess.run(
        [sys.executable, "-c", script, str(marker_path), mode, *args],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def remove_required_provenance(db_path):
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute(
            "UPDATE artifacts SET evidence_json = ? WHERE id = ?",
            (json.dumps([]), "symbol.coder_value_service"),
        )


def test_mcp_serve_forwards_database_and_leaves_stdout_to_server(tmp_path):
    marker_path = tmp_path / "server-db.txt"
    database_path = tmp_path / "knowledge.sqlite"

    result = run_with_patched_mcp_server(
        "mcp", "serve", "--db", str(database_path), marker_path=marker_path
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout == '{"jsonrpc":"2.0","method":"ready"}\n'
    assert marker_path.read_text(encoding="utf-8") == str(database_path)


def test_mcp_serve_reports_missing_optional_sdk_as_structured_error(tmp_path):
    result = run_with_patched_mcp_server(
        "mcp", "serve", "--db", str(tmp_path / "knowledge.sqlite"),
        marker_path=tmp_path / "unused.txt",
        sdk_unavailable=True,
    )

    assert result.returncode == 1
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "MCP_UNAVAILABLE"
    assert "pip install" in error["details"]["hint"]


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


def test_dataset_load_initializes_and_replaces_database(tmp_path, runner):
    db_path = tmp_path / "knowledge.sqlite"
    result = runner("dataset", "load", "--db", str(db_path), "--source", "data/coder_activation.json")

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["loaded"] is True
    assert payload["counts"] == {"artifacts": 9}
    assert payload["db"] == str(db_path)
    assert payload["source"] == "data/coder_activation.json"


def test_dataset_load_rejects_invalid_source_without_destroying_existing_database(seeded_db, tmp_path, runner):
    invalid_source = tmp_path / "broken.json"
    invalid_source.write_text("{", encoding="utf-8")

    result = runner("dataset", "load", "--db", str(seeded_db), "--source", str(invalid_source))

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_DATASET"
    assert json.loads(runner("dataset", "validate", "--db", str(seeded_db)).stdout)["valid"] is True


def test_compile_rejects_non_positive_budget_with_stdout_json(seeded_db, runner):
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate", "--budget", "0")

    assert result.returncode != 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_BUDGET"


def test_compile_requires_exactly_one_task_source(seeded_db, tmp_path, runner):
    task_file = tmp_path / "task.txt"
    task_file.write_text("activate coder values", encoding="utf-8")
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate", "--task-file", str(task_file), "--budget", "5")

    assert result.returncode != 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_INPUT"


def test_evaluate_accepts_data_and_oracle_paths_without_echoing_oracle(seeded_db, tmp_path, runner):
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text('{"secret": "do-not-echo"}', encoding="utf-8")
    result = runner("context", "evaluate", "--db", str(seeded_db), "--case", "coder-activation", "--data-dir", "data", "--oracle-path", str(oracle_path))

    assert result.returncode != 0
    assert result.stderr == ""
    assert "do-not-echo" not in result.stdout
    assert json.loads(result.stdout)["error"]["code"] == "EVALUATION_UNAVAILABLE"


def test_evaluate_with_real_oracle_emits_metrics_only(seeded_db, runner):
    result = runner(
        "context",
        "evaluate",
        "--db",
        str(seeded_db),
        "--case",
        "coder-activation",
        "--oracle-path",
        "data/oracle/coder_activation.json",
    )

    assert result.returncode == 0
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert set(payload) == {"baseline", "case", "compiler", "reproducible", "warnings"}
    assert payload["case"] == "coder-activation"
    assert "expected_artifact_ids" not in result.stdout
    assert "critical_artifact_ids" not in result.stdout
    assert "feature.tenant_coder_activation" not in result.stdout


@pytest.mark.parametrize(("mutation", "issue"), [
    ("DELETE FROM dataset_metadata", "MISSING_METADATA"),
    ("UPDATE dataset_metadata SET generated_at = ' '", "INVALID_METADATA"),
    ("UPDATE facts SET evidence_json = '[null]'", "INVALID_EVIDENCE"),
    ("UPDATE task_profiles SET expected_artifacts_json = '[{}]'", "INVALID_TASK_PROFILE"),
])
def test_compile_cli_reports_malformed_dataset_as_json(seeded_db, runner, mutation, issue):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(mutation)
    result = runner("context", "compile", "--db", str(seeded_db), "--task", "activate coder values", "--budget", "2")
    assert result.returncode == 1
    assert result.stderr == ""
    error = json.loads(result.stdout)["error"]
    assert error["code"] == "DATASET_INVALID"
    assert error["details"]["issues"][0]["code"] == issue


def test_ingest_neo4j_dry_run_emits_fixture_projection_summary(runner):
    result = runner("ingest", "neo4j", "--source", "data/coder_activation.json", "--dry-run")

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "dry_run": True,
        "dataset_version": "0.1.0",
        "nodes": 13,
        "relationships": 25,
        "validated": True,
    }


def test_ingest_neo4j_requires_connection_values_for_live_run(runner):
    password = "not-for-output"
    result = runner(
        "ingest",
        "neo4j",
        "--source",
        "data/coder_activation.json",
        "--password",
        password,
        env={
            "SEKR_NEO4J_URI": None,
            "SEKR_NEO4J_USER": None,
            "SEKR_NEO4J_PASSWORD": None,
        },
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_INPUT"
    assert password not in result.stdout


def test_ingest_neo4j_forwards_exact_environment_connection_values(monkeypatch, capsys):
    from sekr import cli

    adapter = Mock(return_value=IngestSummary(nodes_written=13, relationships_written=25))
    monkeypatch.setattr(cli, "write_projection", adapter)
    monkeypatch.setenv("SEKR_NEO4J_URI", "bolt://example.test:7687")
    monkeypatch.setenv("SEKR_NEO4J_USER", "sekr")
    monkeypatch.setenv("SEKR_NEO4J_PASSWORD", "environment-password")

    assert cli.main(("ingest", "neo4j", "--source", "data/coder_activation.json")) == 0
    assert json.loads(capsys.readouterr().out) == {
        "dry_run": False,
        "dataset_version": "0.1.0",
        "nodes_written": 13,
        "relationships_written": 25,
    }
    _, keyword_arguments = adapter.call_args
    assert keyword_arguments == {
        "uri": "bolt://example.test:7687",
        "user": "sekr",
        "password": "environment-password",
    }


def test_ingest_neo4j_maps_invalid_utf8_to_invalid_dataset(tmp_path, runner):
    source = tmp_path / "invalid-utf8.json"
    source.write_bytes(b"\xff")

    result = runner("ingest", "neo4j", "--source", str(source), "--dry-run")

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_DATASET"


def test_ingest_neo4j_never_emits_live_password_with_adapter_subprocess():
    password = "must-not-appear"
    result = run_with_patched_neo4j_adapter(
        "ingest",
        "neo4j",
        "--source",
        "data/coder_activation.json",
        "--password",
        password,
        "--uri",
        "bolt://example.test:7687",
        "--user",
        "sekr",
        env={},
    )

    assert result.returncode == 0
    assert password not in result.stdout
    assert password not in result.stderr


def test_delta_emits_canonical_json_bytes_to_stdout(binary_runner):
    result = binary_runner("delta", "--base", "HEAD~1", "--head", "HEAD")

    assert result.returncode == 0
    assert result.stderr == b""
    payload = json.loads(result.stdout)
    assert set(payload) == {"base", "head", "files", "symbols", "impact", "commits"}
    assert payload["base"] == "HEAD~1"
    assert payload["head"] == "HEAD"
    assert result.stdout == (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")


def test_delta_output_file_matches_stdout_byte_for_byte(tmp_path, binary_runner):
    stdout_result = binary_runner("delta", "--base", "HEAD~1", "--head", "HEAD")
    output_path = tmp_path / "knowledge-delta.json"
    output_result = binary_runner(
        "delta", "--base", "HEAD~1", "--head", "HEAD", "--output", str(output_path)
    )

    assert stdout_result.returncode == 0
    assert output_result.returncode == 0
    assert output_path.read_bytes() == stdout_result.stdout


def test_delta_output_mode_emits_only_success_summary_to_stderr(tmp_path, runner):
    output_path = tmp_path / "knowledge-delta.json"

    result = runner(
        "delta", "--base", "HEAD~1", "--head", "HEAD", "--output", str(output_path)
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == f"Wrote knowledge delta to {output_path}\n"


def test_delta_invalid_ref_returns_structured_json_without_traceback(runner):
    result = runner("delta", "--base", "not-a-ref", "--head", "HEAD")

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "DELTA_INVALID_REF"


def test_delta_unwritable_output_returns_structured_json(tmp_path, runner):
    output_directory = tmp_path / "output-directory"
    output_directory.mkdir()

    result = runner(
        "delta", "--base", "HEAD~1", "--head", "HEAD", "--output", str(output_directory)
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "DELTA_OUTPUT_ERROR"


def test_delta_command_preserves_context_compile(seeded_db, runner):
    result = runner(
        "context", "compile", "--db", str(seeded_db), "--task", "activate coder values", "--budget", "5"
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["task"] == "activate coder values"


def test_knowledge_check_emits_valid_report_for_identical_snapshots(tmp_path, runner):
    snapshot = {"nodes": [], "relationships": []}
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    current.write_text(json.dumps(snapshot), encoding="utf-8")
    baseline.write_text(json.dumps(snapshot), encoding="utf-8")

    result = runner("knowledge-check", "--input", str(current), "--baseline", str(baseline))

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout)["valid"] is True


def test_knowledge_check_returns_one_and_writes_report_for_drift(tmp_path, runner):
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    output = tmp_path / "report.json"
    current.write_text(json.dumps({"nodes": [{"kind": "Fact", "key": "new", "properties": {}}],
                                   "relationships": []}), encoding="utf-8")
    baseline.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")

    result = runner("knowledge-check", "--input", str(current), "--baseline", str(baseline),
                    "--output", str(output))

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"Wrote knowledge check report to {output}\n"
    assert json.loads(output.read_text(encoding="utf-8"))["valid"] is False


def test_knowledge_check_returns_structured_error_for_malformed_snapshot(tmp_path, runner):
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    current.write_text(json.dumps({"nodes": [{"kind": "Fact"}], "relationships": []}), encoding="utf-8")
    baseline.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")

    result = runner("knowledge-check", "--input", str(current), "--baseline", str(baseline))

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_KNOWLEDGE"


def test_knowledge_snapshot_writes_canonical_baseline(tmp_path, runner):
    output = tmp_path / "baseline.json"

    result = runner("knowledge-snapshot", "--input", "data/coder_activation.json",
                    "--output", str(output))

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == f"Wrote knowledge snapshot to {output}\n"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["nodes"][0]["kind"] == "Dataset"
    assert payload["relationships"]


def test_knowledge_check_report_only_policy_returns_success_for_drift(tmp_path, runner):
    current = tmp_path / "current.json"
    baseline = tmp_path / "baseline.json"
    policy = tmp_path / "policy.json"
    current.write_text(json.dumps({"nodes": [{"kind": "Fact", "key": "new", "properties": {}}],
                                   "relationships": []}), encoding="utf-8")
    baseline.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")
    policy.write_text(json.dumps({"mode": "report-only"}), encoding="utf-8")

    result = runner("knowledge-check", "--input", str(current), "--baseline", str(baseline),
                    "--policy", str(policy))

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["valid"] is False
    assert payload["policy"] == {"mode": "report-only", "allowed": True, "severity": "warning"}


def _content_hash(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def test_knowledge_freshness_accepts_dataset_input_and_uses_fixed_as_of(runner):
    """Removing structured dataset loading or UTC parsing must fail this CLI contract."""
    result = runner(
        "knowledge-freshness",
        "--input",
        "data/coder_activation.json",
        "--as-of",
        "2026-09-11T07:00:00-05:00",
    )

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["as_of"] == "2026-09-11T12:00:00Z"
    assert payload["valid"] is False
    assert payload["counts"]["unverified"] > 0


def test_knowledge_freshness_writes_exact_stdout_bytes_for_current_snapshot(tmp_path, runner, binary_runner):
    """Changing serialization, output routing, or valid exit handling must fail this command contract."""
    evidence = tmp_path / "evidence.md"
    evidence.write_bytes(b"current evidence")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "kind": "Fact",
                        "key": "current",
                        "properties": {
                            "evidence": ["evidence.md"],
                            "content_hash": _content_hash(b"current evidence"),
                        },
                    }
                ],
                "relationships": [],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "freshness.json"
    arguments = (
        "knowledge-freshness",
        "--input",
        str(snapshot),
        "--as-of",
        "2026-09-11T12:00:00Z",
    )

    stdout_result = binary_runner(*arguments)
    output_result = runner(*arguments, "--output", str(output))

    assert stdout_result.returncode == 0
    assert output_result.returncode == 0
    assert output_result.stdout == ""
    assert output_result.stderr == f"Wrote knowledge freshness report to {output}\n"
    assert output.read_bytes() == stdout_result.stdout
    assert json.loads(stdout_result.stdout)["valid"] is True


def test_knowledge_freshness_returns_one_for_non_current_records_without_evidence_paths(tmp_path, runner):
    """Returning success for stale records or exposing resolved evidence paths must fail this contract."""
    evidence = tmp_path / "evidence.md"
    evidence.write_bytes(b"stale evidence")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "kind": "Fact",
                        "key": "stale",
                        "properties": {
                            "evidence": ["evidence.md"],
                            "content_hash": _content_hash(b"stale evidence"),
                            "valid_until": "2026-09-10T00:00:00Z",
                        },
                    }
                ],
                "relationships": [],
            }
        ),
        encoding="utf-8",
    )

    result = runner(
        "knowledge-freshness",
        "--input",
        str(snapshot),
        "--as-of",
        "2026-09-11T12:00:00Z",
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["records"] == [
        {"kind": "Fact", "key": "stale", "state": "stale", "reasons": ["VALIDITY_EXPIRED"]}
    ]
    assert str(tmp_path) not in result.stdout


def test_knowledge_freshness_invalid_as_of_returns_structured_error(runner):
    """Accepting a naive or malformed timestamp must fail this provenance-validation contract."""
    result = runner(
        "knowledge-freshness",
        "--input",
        "data/coder_activation.json",
        "--as-of",
        "2026-09-11T12:00:00",
    )

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_PROVENANCE"


def test_knowledge_freshness_unwritable_output_returns_structured_error(tmp_path, runner):
    """Masking a failed report write as success must fail this output-error contract."""
    result = runner(
        "knowledge-freshness",
        "--input",
        "data/coder_activation.json",
        "--as-of",
        "2026-09-11T12:00:00Z",
        "--output",
        str(tmp_path / "missing" / "freshness.json"),
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"


def test_knowledge_freshness_never_overwrites_input(tmp_path, runner):
    snapshot = tmp_path / "snapshot.json"
    original = json.dumps({"nodes": [], "relationships": []})
    snapshot.write_text(original, encoding="utf-8")

    result = runner("knowledge-freshness", "--input", str(snapshot), "--as-of", "2026-09-11T12:00:00Z", "--output", str(snapshot))

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert snapshot.read_text(encoding="utf-8") == original


def test_knowledge_freshness_never_overwrites_approved_baseline(tmp_path, runner):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text("approved", encoding="utf-8")

    result = runner("knowledge-freshness", "--input", str(snapshot), "--as-of", "2026-09-11T12:00:00Z", "--output", str(baseline), env={"SEKR_KNOWLEDGE_BASELINE": str(baseline)})

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert baseline.read_text(encoding="utf-8") == "approved"


def test_knowledge_freshness_rejects_existing_sqlite_output_from_any_cwd(tmp_path, runner):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")
    sqlite_path = tmp_path / "knowledge.sqlite"
    sqlite_path.write_bytes(b"SQLite format 3\x00" + b"protected")

    result = runner(
        "knowledge-freshness", "--input", str(snapshot), "--as-of", "2026-09-11T12:00:00Z",
        "--output", str(sqlite_path), cwd=Path(__file__).parent.parent.parent,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert sqlite_path.read_bytes().startswith(b"SQLite format 3")


def test_knowledge_freshness_rejects_existing_dataset_source_output(tmp_path, runner):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "metadata": {"version": "v", "source_commit": "c", "generated_at": "now"},
        "artifacts": [], "relations": [], "facts": [], "task_profiles": [],
    }), encoding="utf-8")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")

    result = runner(
        "knowledge-freshness", "--input", str(snapshot), "--as-of", "2026-09-11T12:00:00Z",
        "--output", str(source), cwd=Path(__file__).parent.parent.parent,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"


def test_knowledge_freshness_rejects_hardlink_alias_to_source_with_different_suffix(tmp_path, runner):
    source = tmp_path / "source.json"
    source.write_text(json.dumps({
        "metadata": {"version": "v", "source_commit": "c", "generated_at": "now"},
        "artifacts": [], "relations": [], "facts": [], "task_profiles": [],
    }), encoding="utf-8")
    output = tmp_path / "report.output"
    os.link(source, output)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")
    original = source.read_bytes()

    result = runner(
        "knowledge-freshness", "--input", str(snapshot), "--as-of", "2026-09-11T00:00:00Z",
        "--output", str(output), cwd=Path(__file__).parent.parent.parent,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert source.read_bytes() == original


def test_knowledge_freshness_reports_invalid_snapshot_structure(tmp_path, runner):
    source = tmp_path / "invalid.json"
    source.write_text(json.dumps({"nodes": [{}], "relationships": []}), encoding="utf-8")

    result = runner("knowledge-freshness", "--input", str(source), "--as-of", "2026-09-11T12:00:00Z")

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "INVALID_KNOWLEDGE"


def test_knowledge_check_accepts_committed_legacy_baseline(runner):
    result = runner(
        "knowledge-check", "--input", "data/coder_activation.json",
        "--baseline", "data/knowledge-baseline.json",
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "error" not in payload
    assert "policy" in payload


def test_knowledge_freshness_reports_committed_legacy_baseline(runner):
    result = runner(
        "knowledge-freshness", "--input", "data/knowledge-baseline.json",
        "--as-of", "2026-09-11T00:00:00Z",
    )

    assert result.returncode in {0, 1}
    assert "error" not in json.loads(result.stdout)


def test_knowledge_freshness_rejects_output_colliding_with_referenced_evidence(tmp_path, runner):
    evidence = tmp_path / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [{"kind": "Fact", "key": "f", "properties": {
        "evidence": ["evidence.md"], "content_hash": "sha256:" + "0" * 64,
    }}], "relationships": []}), encoding="utf-8")
    original = evidence.read_bytes()

    result = runner(
        "knowledge-freshness", "--input", str(snapshot),
        "--as-of", "2026-09-11T00:00:00Z", "--output", str(evidence),
        cwd=Path(__file__).parent.parent.parent,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert evidence.read_bytes() == original


def test_knowledge_freshness_rejects_hardlink_to_referenced_evidence(tmp_path, runner):
    evidence = tmp_path / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    output = tmp_path / "freshness.json"
    os.link(evidence, output)
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [{"kind": "Fact", "key": "f", "properties": {
        "evidence": ["evidence.md"], "content_hash": "sha256:" + "0" * 64,
    }}], "relationships": []}), encoding="utf-8")
    original = evidence.read_bytes()

    result = runner(
        "knowledge-freshness", "--input", str(snapshot),
        "--as-of", "2026-09-11T00:00:00Z", "--output", str(output),
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert evidence.read_bytes() == original


def test_knowledge_freshness_rejects_hardlink_to_input(tmp_path, runner):
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"nodes": [], "relationships": []}), encoding="utf-8")
    output = tmp_path / "freshness.json"
    os.link(snapshot, output)
    original = snapshot.read_bytes()

    result = runner(
        "knowledge-freshness", "--input", str(snapshot),
        "--as-of", "2026-09-11T00:00:00Z", "--output", str(output),
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error"]["code"] == "KNOWLEDGE_OUTPUT_ERROR"
    assert snapshot.read_bytes() == original
