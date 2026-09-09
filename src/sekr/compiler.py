"""Deterministic, evidence-aware compilation of SEKR context packages."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Iterable, Mapping, Sequence

from sekr.db import KnowledgeRepository, SearchCandidate, normalize_tokens, validate_dataset
from sekr.errors import StructuredError
from sekr.models import (
    ContextItem,
    ContextPackage,
    EvaluationMetrics,
    EvaluationReport,
    KnowledgeFact,
)


TERM_MATCH_WEIGHT = 0.40
RELATION_PROXIMITY_WEIGHT = 0.20
ARTIFACT_TYPE_WEIGHT = 0.15
EVIDENCE_QUALITY_WEIGHT = 0.10
CONFIDENCE_WEIGHT = 0.10
FRESHNESS_WEIGHT = 0.05

WEIGHTS = {
    "term_match": TERM_MATCH_WEIGHT,
    "relation_proximity": RELATION_PROXIMITY_WEIGHT,
    "artifact_type": ARTIFACT_TYPE_WEIGHT,
    "evidence_quality": EVIDENCE_QUALITY_WEIGHT,
    "confidence": CONFIDENCE_WEIGHT,
    "freshness": FRESHNESS_WEIGHT,
}

_VERB_NORMALIZATION = {
    "activation": "activate",
    "activates": "activate",
    "activated": "activate",
    "activating": "activate",
    "deactivation": "deactivate",
    "deactivates": "deactivate",
    "deactivated": "deactivate",
    "deactivating": "deactivate",
}
_ACTIVE_CONCEPTS = {"active", "inactive"}
_ARTIFACT_RELEVANCE = {
    "symbol": 1.0,
    "test": 0.95,
    "endpoint": 0.85,
    "feature": 0.80,
    "repository": 0.75,
    "table": 0.70,
    "adr": 0.65,
    "requirement": 0.65,
    "document": 0.50,
    "component": 0.30,
    "fact": 0.45,
}
_CONFIDENCE_QUALITY = {
    "VERIFIED": 1.0,
    "APPROVED": 0.90,
    "INFERRED": 0.60,
    "STALE": 0.35,
    "CONFLICTED": 0.0,
    "UNKNOWN": 0.0,
}
_EVALUATION_TASKS = {"coder-activation": "activate coder values"}


@dataclass(frozen=True)
class RankedCandidate:
    candidate: SearchCandidate
    score: float
    components: Mapping[str, float]
    explanation: Sequence[str]


def tokenize_task(task: str) -> tuple[str, ...]:
    """Normalize task language and add the activation-state domain concepts."""
    normalized: list[str] = []
    for token in normalize_tokens([task]):
        normalized.append(_VERB_NORMALIZATION.get(token, token))
    if _ACTIVE_CONCEPTS.intersection(normalized):
        normalized.extend(sorted(_ACTIVE_CONCEPTS))
    if {"activate", "deactivate"}.intersection(normalized):
        normalized.extend(sorted(_ACTIVE_CONCEPTS))
    return normalize_tokens(normalized)


def evaluate_case(
    db_path: str,
    oracle_path: str,
    *,
    case: str,
    budget: int,
) -> EvaluationReport:
    """Evaluate compiler retrieval against a local oracle and text baseline."""
    task = _EVALUATION_TASKS.get(case)
    if task is None:
        raise StructuredError("EVALUATION_UNAVAILABLE", "Unknown evaluation case", {"case": case})
    expected_ids, critical_ids = _read_oracle(oracle_path)
    repository = KnowledgeRepository(db_path)
    compiler = ContextCompiler(repository)
    first = compiler.compile(task, budget)
    second = compiler.compile(task, budget)
    baseline_ids = _text_baseline_ids(repository.path, task, budget)
    with sqlite3.connect(repository.path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute("SELECT * FROM artifacts ORDER BY id").fetchall()
    artifacts = {
        row["id"]: {
            "id": row["id"], "artifactType": row["artifact_type"], "title": row["title"],
            "description": row["description"], "path": row["path"],
            "evidence": json.loads(row["evidence_json"]), "confidence": row["confidence"],
        }
        for row in rows
    }
    universe = frozenset(artifacts)
    if not expected_ids <= universe or not critical_ids <= expected_ids:
        raise StructuredError("EVALUATION_UNAVAILABLE", "Oracle IDs must belong to the dataset and critical IDs must be expected")
    return EvaluationReport(
        case=case,
        compiler=_metrics((item.id for item in first.items), expected_ids, critical_ids, universe, first.to_dict()),
        baseline=_metrics(baseline_ids, expected_ids, critical_ids, universe, [artifacts[identifier] for identifier in baseline_ids]),
        reproducible=first.to_dict() == second.to_dict(),
    )


def _read_oracle(oracle_path: str) -> tuple[frozenset[str], frozenset[str]]:
    try:
        payload = json.loads(open(oracle_path, encoding="utf-8").read())
        expected_ids = frozenset(payload["expected_artifact_ids"])
        critical_ids = frozenset(payload["critical_artifact_ids"])
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise StructuredError(
            "EVALUATION_UNAVAILABLE",
            "Evaluation oracle is unavailable or invalid",
        ) from error
    if not all(isinstance(identifier, str) for identifier in expected_ids | critical_ids):
        raise StructuredError("EVALUATION_UNAVAILABLE", "Evaluation oracle is invalid")
    return expected_ids, critical_ids


def _text_baseline_ids(db_path: str, task: str, budget: int) -> tuple[str, ...]:
    task_tokens = set(normalize_tokens([task]))
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, title, description, path, evidence_json FROM artifacts ORDER BY id"
        ).fetchall()
    ranked = []
    for artifact_id, title, description, path, evidence_json in rows:
        text = " ".join((artifact_id, title, description, path or "", *json.loads(evidence_json)))
        overlap = len(task_tokens.intersection(normalize_tokens((text,)))) / max(len(task_tokens), 1)
        ranked.append((artifact_id, overlap))
    return tuple(artifact_id for artifact_id, _ in sorted(ranked, key=lambda item: (-item[1], item[0]))[:budget])


def _metrics(
    selected_ids: Iterable[str], expected_ids: frozenset[str], critical_ids: frozenset[str],
    universe: frozenset[str], context: object,
) -> EvaluationMetrics:
    """FPR = FP / (FP + TN) over all dataset artifacts; no negatives yields 0.

    Bytes measure compact, sorted-key, UTF-8 JSON without a trailing newline.
    Context is the compiler package or the baseline's selected artifact records.
    """
    selected = tuple(selected_ids)
    selected_set = frozenset(selected)
    false_positive_ids = tuple(identifier for identifier in selected if identifier not in expected_ids)
    negative_ids = universe - expected_ids
    return EvaluationMetrics(
        precision_at_k=len(selected_set & expected_ids) / len(selected) if selected else 0.0,
        critical_recall=len(selected_set & critical_ids) / len(critical_ids) if critical_ids else 0.0,
        context_size=len(selected),
        false_positive_rate=len(false_positive_ids) / len(negative_ids) if negative_ids else 0.0,
        false_positive_ids=false_positive_ids,
        context_size_bytes=len(json.dumps(context, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")),
        candidate_count=len(universe),
        true_negative_count=len(negative_ids - selected_set),
    )


class ContextCompiler:
    """Rank repository candidates and apply a deterministic context budget."""

    def __init__(self, repository: KnowledgeRepository) -> None:
        self.repository = repository

    def compile(self, task: str, budget: int) -> ContextPackage:
        self._validate_input(task, budget)
        validation = validate_dataset(self.repository.path)
        if not validation.valid:
            raise StructuredError(
                "DATASET_INVALID", "Dataset validation failed",
                {"issues": [error.to_dict() for error in validation.errors],
                 "counts": {"artifacts": validation.artifact_count}},
            )
        task_tokens = tokenize_task(task)
        candidates = self.repository.search_candidates(task_tokens)
        facts_by_artifact = self._facts_by_artifact(
            candidate.artifact.id for candidate in candidates
        )
        ranked = sorted(
            (
                self.score(candidate, task_tokens, facts_by_artifact)
                for candidate in candidates
            ),
            key=lambda result: (-result.score, result.candidate.artifact.id),
        )
        selected = ranked[:budget]
        selected_facts = {
            item.candidate.artifact.id: facts_by_artifact.get(item.candidate.artifact.id, ())
            for item in selected
        }
        items = tuple(
            self._context_item(item, selected_facts[item.candidate.artifact.id])
            for item in selected
        )
        conflicts = self._conflicts(items, selected_facts)
        warnings = self._warnings(candidates, selected, items, conflicts)
        sections = self._sections(items, selected_facts, conflicts)
        return ContextPackage(
            task=task,
            items=items,
            budget=budget,
            omitted_count=max(len(ranked) - len(selected), 0),
            warnings=warnings,
            **sections,
        )

    @staticmethod
    def _validate_input(task: object, budget: object) -> None:
        if not isinstance(task, str) or not task.strip():
            raise StructuredError("INVALID_TASK", "Task must be non-empty text")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            raise StructuredError("INVALID_BUDGET", "Budget must be a non-negative integer")

    def score(
        self,
        candidate: SearchCandidate,
        task_tokens: Sequence[str],
        facts_by_artifact: Mapping[str, Sequence[KnowledgeFact]] | None = None,
    ) -> RankedCandidate:
        artifact = candidate.artifact
        artifact_tokens = set(normalize_tokens((artifact.id, artifact.title, artifact.description, artifact.path or "")))
        requested = set(task_tokens)
        term_match = len(requested.intersection(artifact_tokens)) / max(len(requested), 1)
        relation_proximity = 1.0 if any(entry.startswith("relation:1:") for entry in candidate.score_evidence) else 0.5 if any(entry.startswith("relation:2:") for entry in candidate.score_evidence) else 0.0
        # Attached facts are the facts returned with this candidate, so their
        # quality contributes equally with the artifact's own quality.
        facts = facts_by_artifact.get(artifact.id, ()) if facts_by_artifact is not None else ()
        records = (artifact, *facts)
        components = {
            "term_match": TERM_MATCH_WEIGHT * term_match,
            "relation_proximity": RELATION_PROXIMITY_WEIGHT * relation_proximity,
            "artifact_type": ARTIFACT_TYPE_WEIGHT * _ARTIFACT_RELEVANCE[artifact.artifact_type],
            "evidence_quality": EVIDENCE_QUALITY_WEIGHT * sum(bool(record.evidence) for record in records) / len(records),
            "confidence": CONFIDENCE_WEIGHT * sum(_CONFIDENCE_QUALITY[record.confidence] for record in records) / len(records),
            "freshness": FRESHNESS_WEIGHT * sum(fact.freshness == "current" for fact in facts) / max(len(facts), 1),
        }
        explanation = (
            "weights:" + json.dumps(WEIGHTS, sort_keys=True, separators=(",", ":")),
            *(f"component:{name}={value:.4f}" for name, value in components.items()),
            *candidate.score_evidence,
        )
        return RankedCandidate(candidate, sum(components.values()), components, explanation)

    def _facts_by_artifact(self, artifact_ids: Iterable[str]) -> dict[str, tuple[KnowledgeFact, ...]]:
        ids = tuple(sorted(set(artifact_ids)))
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        with sqlite3.connect(self.repository.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                f"SELECT * FROM facts WHERE artifact_id IN ({placeholders}) ORDER BY id", ids
            ).fetchall()
        facts: dict[str, list[KnowledgeFact]] = {}
        for row in rows:
            facts.setdefault(row["artifact_id"], []).append(
                KnowledgeFact(
                    id=row["id"], statement=row["statement"], source=row["source"],
                    evidence=json.loads(row["evidence_json"]), confidence=row["confidence"],
                    freshness=row["freshness"], source_version=row["source_version"],
                    valid_from=row["valid_from"], scope=row["scope"], owner=row["owner"],
                )
            )
        return {artifact_id: tuple(records) for artifact_id, records in facts.items()}

    @staticmethod
    def _context_item(ranked: RankedCandidate, facts: Sequence[KnowledgeFact]) -> ContextItem:
        artifact = ranked.candidate.artifact
        return ContextItem(
            id=artifact.id, artifact_type=artifact.artifact_type, title=artifact.title,
            relevance_score=ranked.score, confidence=artifact.confidence,
            evidence=tuple(artifact.evidence), facts=tuple(facts),
            why_included=ranked.explanation, content=artifact.description, path=artifact.path,
        )

    @staticmethod
    def _warnings(candidates, selected, items, conflicts) -> tuple[str, ...]:
        warnings: list[str] = []
        if len(selected) < len(candidates):
            warnings.append("budget_truncated")
        if not candidates:
            warnings.append("no_candidates")
        if any(not item.evidence or any(not fact.evidence for fact in item.facts) for item in items):
            warnings.append("missing_evidence")
        if conflicts:
            warnings.append("conflicts")
        return tuple(warnings)

    @staticmethod
    def _conflicts(items: Sequence[ContextItem], facts_by_artifact) -> tuple[str, ...]:
        artifact_conflicts = tuple(
            f"artifact:{item.id}"
            for item in items
            if item.confidence == "CONFLICTED"
        )
        fact_conflicts = tuple(
            f"fact:{fact.id}"
            for records in facts_by_artifact.values()
            for fact in records
            if fact.confidence == "CONFLICTED"
        )
        return artifact_conflicts + fact_conflicts

    @staticmethod
    def _sections(items, facts_by_artifact, conflicts):
        by_type: dict[str, list[str]] = {}
        for item in items:
            by_type.setdefault(item.artifact_type, []).append(item.id)
        facts = tuple(fact for records in facts_by_artifact.values() for fact in records)
        return {
            "requirements": tuple(by_type.get("feature", ())) + facts,
            "architectural_constraints": tuple(by_type.get("adr", ())) + tuple(by_type.get("document", ())),
            "relevant_symbols": tuple(by_type.get("symbol", ())),
            "execution_flows": tuple(by_type.get("endpoint", ())),
            "persistence_schema": tuple(by_type.get("repository", ())) + tuple(by_type.get("table", ())),
            "tests": tuple(by_type.get("test", ())),
            "risks": (),
            "conflicts": conflicts,
        }
