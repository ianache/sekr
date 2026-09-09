"""Frozen domain contracts for the SEKR Context Compiler."""

from dataclasses import dataclass, fields, is_dataclass
from typing import Any, Literal, Mapping, Sequence

from sekr.errors import StructuredError


Confidence = Literal[
    "VERIFIED",
    "APPROVED",
    "INFERRED",
    "STALE",
    "CONFLICTED",
    "UNKNOWN",
]
ArtifactType = Literal[
    "feature",
    "symbol",
    "endpoint",
    "table",
    "test",
    "requirement",
    "component",
    "adr",
    "document",
    "fact",
    "repository",
]

_ARTIFACT_TYPES = frozenset(
    {
        "feature",
        "symbol",
        "endpoint",
        "table",
        "test",
        "requirement",
        "component",
        "adr",
        "document",
        "fact",
        "repository",
    }
)
_CONFIDENCES = frozenset(
    {"VERIFIED", "APPROVED", "INFERRED", "STALE", "CONFLICTED", "UNKNOWN"}
)


def _validate_artifact_type(value: str, field_name: str = "artifact_type") -> None:
    if value not in _ARTIFACT_TYPES:
        raise StructuredError(
            "INVALID_ARTIFACT_TYPE",
            f"Unsupported artifact type: {value!r}",
            {"field": field_name, "value": value},
        )


def _normalize_confidence(
    confidence: str, evidence: Sequence[str], field_name: str = "confidence"
) -> str:
    if confidence not in _CONFIDENCES:
        raise StructuredError(
            "INVALID_CONFIDENCE",
            f"Unsupported confidence: {confidence!r}",
            {"field": field_name, "value": confidence},
        )
    if confidence in {"APPROVED", "VERIFIED"} and not evidence:
        return "UNKNOWN"
    return confidence


def _camel_case(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _json_value(value: Any) -> Any:
    if is_dataclass(value):
        return {
            _camel_case(item.name): _json_value(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


class _Serializable:
    def to_dict(self) -> dict[str, Any]:
        return _json_value(self)


@dataclass(frozen=True)
class Artifact(_Serializable):
    id: str
    artifact_type: ArtifactType
    title: str
    description: str = ""
    path: str | None = None
    evidence: Sequence[str] = ()
    confidence: Confidence = "UNKNOWN"

    def __post_init__(self) -> None:
        _validate_artifact_type(self.artifact_type)
        object.__setattr__(
            self, "confidence", _normalize_confidence(self.confidence, self.evidence)
        )


@dataclass(frozen=True)
class Relation(_Serializable):
    id: str
    source_id: str
    target_id: str
    relation_type: str
    evidence: Sequence[str] = ()
    confidence: Confidence = "UNKNOWN"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "confidence", _normalize_confidence(self.confidence, self.evidence)
        )


@dataclass(frozen=True)
class KnowledgeFact(_Serializable):
    id: str
    statement: str
    source: str = ""
    evidence: Sequence[str] = ()
    confidence: Confidence = "UNKNOWN"
    freshness: str | None = None
    source_version: str = ""
    valid_from: str | None = None
    scope: str = ""
    owner: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "confidence", _normalize_confidence(self.confidence, self.evidence)
        )


@dataclass(frozen=True)
class TaskProfile(_Serializable):
    id: str
    name: str
    terms: Sequence[str] = ()
    expected_artifact_types: Sequence[ArtifactType] = ()
    expected_artifacts: Sequence[str] = ()

    def __post_init__(self) -> None:
        for artifact_type in self.expected_artifact_types:
            _validate_artifact_type(artifact_type, "expected_artifact_types")


@dataclass(frozen=True)
class DatasetMetadata(_Serializable):
    version: str
    source_commit: str = ""
    generated_at: str = ""
    description: str = ""


@dataclass(frozen=True)
class ContextItem(_Serializable):
    id: str
    artifact_type: ArtifactType
    title: str
    relevance_score: float
    confidence: Confidence
    evidence: Sequence[str] = ()
    why_included: Sequence[str] = ()
    content: str = ""
    path: str | None = None
    facts: Sequence[KnowledgeFact] = ()

    def __post_init__(self) -> None:
        _validate_artifact_type(self.artifact_type)
        object.__setattr__(
            self, "confidence", _normalize_confidence(self.confidence, self.evidence)
        )


@dataclass(frozen=True)
class ContextPackage(_Serializable):
    task: str
    items: Sequence[ContextItem]
    budget: int
    omitted_count: int = 0
    warnings: Sequence[str] = ()
    requirements: Sequence[str | KnowledgeFact] = ()
    architectural_constraints: Sequence[str] = ()
    relevant_symbols: Sequence[str] = ()
    execution_flows: Sequence[str] = ()
    persistence_schema: Sequence[str] = ()
    tests: Sequence[str] = ()
    risks: Sequence[str] = ()
    conflicts: Sequence[str] = ()


@dataclass(frozen=True)
class EvaluationMetrics(_Serializable):
    precision_at_k: float = 0.0
    critical_recall: float = 0.0
    context_size: int = 0
    false_positive_rate: float = 0.0
    false_positive_ids: Sequence[str] = ()
    context_size_bytes: int = 0
    candidate_count: int = 0
    true_negative_count: int = 0


@dataclass(frozen=True)
class EvaluationReport(_Serializable):
    case: str
    compiler: EvaluationMetrics
    baseline: EvaluationMetrics
    reproducible: bool = True
    warnings: Sequence[str] = ()
