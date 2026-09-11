from pathlib import Path
import json
import sqlite3

import pytest

from sekr.compiler import ContextCompiler, tokenize_task
from sekr.db import KnowledgeRepository, init_db, load_dataset
from sekr.errors import StructuredError


@pytest.fixture
def seeded_db(tmp_path):
    db_path = tmp_path / "knowledge.sqlite"
    init_db(db_path)
    load_dataset(db_path, Path("data/coder_activation.json"))
    return db_path


def test_compile_prioritizes_active_filter_service_and_test(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "Allow activation and deactivation of Coder values and exclude inactive values",
        budget=6,
    )
    ids = [item.id for item in package.items]
    assert "symbol.coder_value_service" in ids
    assert "test.active_values_exclude_inactive" in ids
    assert "component.billing_invoice_export" not in ids
    assert all(item.evidence for item in package.items)
    candidate_ids = {
        candidate.artifact.id
        for candidate in KnowledgeRepository(seeded_db).search_candidates(
            ["activation", "deactivation", "coder", "values", "inactive"]
        )
    }
    assert "component.billing_invoice_export" not in candidate_ids


def test_compile_reports_omitted_candidates_when_budget_is_small(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile(
        "activate coder values", budget=2
    )
    assert len(package.items) == 2
    assert package.omitted_count > 0
    assert "budget_truncated" in package.warnings


def test_score_returns_fixed_weighted_components_and_explanation(seeded_db):
    compiler = ContextCompiler(KnowledgeRepository(seeded_db))
    candidate = compiler.repository.search_candidates(["activate", "coder"])[0]

    ranked = compiler.score(candidate, ("activate", "coder", "active"))

    assert ranked.score == sum(ranked.components.values())
    assert ranked.components["term_match"] > 0
    assert any(reason.startswith("weights:") for reason in ranked.explanation)


@pytest.mark.parametrize("task", ["", "   ", None, 42])
def test_compile_rejects_empty_or_malformed_task(seeded_db, task):
    with pytest.raises(StructuredError) as error:
        ContextCompiler(KnowledgeRepository(seeded_db)).compile(task, budget=2)

    assert error.value.code == "INVALID_TASK"


def test_compile_rejects_negative_budget(seeded_db):
    with pytest.raises(StructuredError) as error:
        ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", budget=-1)

    assert error.value.code == "INVALID_BUDGET"


def test_compile_reports_no_candidates(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("quantum entanglement", budget=3)

    assert package.items == ()
    assert package.omitted_count == 0
    assert package.warnings == ("no_candidates",)


def test_compile_warns_when_selected_artifact_has_missing_evidence(seeded_db):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "UPDATE artifacts SET evidence_json = ?, confidence = ? WHERE id = ?",
            (json.dumps([]), "UNKNOWN", "endpoint.coder_values"),
        )

    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", budget=8)

    assert "missing_evidence" in package.warnings
    assert next(item for item in package.items if item.id == "endpoint.coder_values").confidence == "UNKNOWN"


def test_compile_preserves_conflicted_artifact_and_fact_details(seeded_db):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(
            "UPDATE artifacts SET confidence = ? WHERE id = ?",
            ("CONFLICTED", "symbol.coder_value_service"),
        )
        connection.execute(
            "UPDATE facts SET confidence = ? WHERE id = ?",
            ("CONFLICTED", "fact.active_query_filters_state"),
        )

    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", budget=8)

    assert "conflicts" in package.warnings
    assert package.conflicts == (
        "artifact:symbol.coder_value_service",
        "fact:fact.active_query_filters_state",
    )


def test_compile_constructs_sections_from_artifacts_and_facts(seeded_db):
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", budget=8)

    assert "feature.tenant_coder_activation" in package.requirements
    assert any(getattr(entry, "statement", None) == "Deactivation marks a Tenant Coder value inactive and preserves history." for entry in package.requirements)
    assert "symbol.coder_value_service" in package.relevant_symbols
    assert "endpoint.coder_values" in package.execution_flows
    assert set(package.persistence_schema) == {
        "repository.tenant_coder_repository",
        "table.tenant_coder_values",
    }
    assert package.tests == ("test.active_values_exclude_inactive",)
    assert package.architectural_constraints == ("document.adr_coder_activation",)


def test_tokenize_task_normalizes_verbs_and_activation_state_terms():
    assert tokenize_task("Activation DEACTIVATED Coder") == (
        "activate",
        "deactivate",
        "coder",
        "active",
        "inactive",
    )


def test_compile_orders_equal_scores_by_artifact_id(seeded_db):
    rows = [
        ("symbol.tie_alpha", "symbol", "Tie alpha", "tie", None, json.dumps(["test:1"]), "VERIFIED"),
        ("symbol.tie_beta", "symbol", "Tie beta", "tie", None, json.dumps(["test:1"]), "VERIFIED"),
    ]
    with sqlite3.connect(seeded_db) as connection:
        connection.executemany(
            "INSERT INTO artifacts (id, artifact_type, title, description, path, evidence_json, confidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("tie", budget=2)

    assert [item.id for item in package.items] == ["symbol.tie_alpha", "symbol.tie_beta"]


def test_compile_preserves_fact_provenance_in_sections_and_items(seeded_db):
    payload = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", 8).to_dict()
    fact = next(entry for entry in payload["requirements"] if isinstance(entry, dict) and entry["id"] == "fact.active_query_filters_state")
    assert fact == {
        "id": "fact.active_query_filters_state",
        "statement": "Active values queries must exclude inactive Tenant Coder values.",
        "source": "Service regression test",
        "evidence": ["tenant/tests/test_coder_value_service.py:44-78"],
        "confidence": "VERIFIED", "freshness": "current", "sourceVersion": "0.1",
        "validFrom": None, "contentHash": None, "observedAt": None, "validUntil": None,
        "scope": "Tenant Coder activation", "owner": "Tenant domain",
    }
    service = next(item for item in payload["items"] if item["id"] == "symbol.coder_value_service")
    assert service["facts"] == [fact]


@pytest.mark.parametrize("confidence", ["UNKNOWN", "CONFLICTED"])
def test_compile_warns_on_evidence_free_fact_despite_artifact_evidence(seeded_db, confidence):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("UPDATE facts SET evidence_json = '[]', confidence = ?", (confidence,))
    payload = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", 8).to_dict()
    assert "missing_evidence" in payload["warnings"]
    facts = [entry for entry in payload["requirements"] if isinstance(entry, dict)]
    assert facts and all(fact["confidence"] == confidence and fact["evidence"] == [] for fact in facts)


@pytest.mark.parametrize(("field", "value"), [("confidence", "UNKNOWN"), ("freshness", "stale")])
def test_fact_quality_changes_ranking(seeded_db, field, value):
    with sqlite3.connect(seeded_db) as connection:
        connection.executemany(
            "INSERT INTO artifacts (id, artifact_type, title, description, path, evidence_json, confidence) VALUES (?, 'symbol', 'Tie', 'tie', NULL, '[\"source:1\"]', 'VERIFIED')",
            [("tie.a",), ("tie.b",)],
        )
        connection.executemany("INSERT INTO facts (id, artifact_id, statement, evidence_json, confidence, freshness) VALUES (?, ?, 'tie fact', '[\"source:2\"]', 'VERIFIED', 'current')", [("fact.a", "tie.a"), ("fact.b", "tie.b")])
    compiler = ContextCompiler(KnowledgeRepository(seeded_db))
    assert [item.id for item in compiler.compile("tie", 2).items] == ["tie.a", "tie.b"]
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(f"UPDATE facts SET {field} = ? WHERE id = 'fact.a'", (value,))
    assert [item.id for item in compiler.compile("tie", 2).items] == ["tie.b", "tie.a"]


@pytest.mark.parametrize(("mutation", "issue"), [
    ("DELETE FROM dataset_metadata", "MISSING_METADATA"),
    ("UPDATE dataset_metadata SET source_commit = ' '", "INVALID_METADATA"),
    ("UPDATE artifacts SET evidence_json = '[null]'", "INVALID_EVIDENCE"),
    ("UPDATE relations SET evidence_json = '[\"\"]'", "INVALID_EVIDENCE"),
    ("UPDATE facts SET evidence_json = '{'", "INVALID_EVIDENCE"),
    ("UPDATE task_profiles SET expected_artifacts_json = '[{}]'", "INVALID_TASK_PROFILE"),
])
def test_compile_validates_dataset_before_retrieval(seeded_db, mutation, issue):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute(mutation)
    with pytest.raises(StructuredError) as error:
        ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", 2)
    assert error.value.code == "DATASET_INVALID"
    assert error.value.details["issues"][0]["code"] == issue


def test_empty_facts_batch_does_not_trigger_per_candidate_queries(seeded_db, monkeypatch):
    with sqlite3.connect(seeded_db) as connection:
        connection.execute("DELETE FROM facts")
    statements = []
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    package = ContextCompiler(KnowledgeRepository(seeded_db)).compile("activate coder values", 8)
    assert len(package.items) == 8
    fact_queries = [sql for sql in statements if "FROM FACTS" in sql.upper() and "WHERE ARTIFACT_ID IN" in sql.upper()]
    assert len(fact_queries) == 1
