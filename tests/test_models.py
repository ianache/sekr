import pytest

from sekr.errors import StructuredError
from sekr.models import Artifact, ContextItem, ContextPackage, TaskProfile


def test_context_item_serializes_provenance_and_reason():
    item = ContextItem(
        id="symbol.coder_value_service",
        artifact_type="symbol",
        title="CoderValueService",
        relevance_score=0.92,
        confidence="APPROVED",
        evidence=["tenant/src/coder_value_service.py:10-42"],
        why_included=["matches_domain", "related_to_active_filter"],
    )
    assert item.to_dict()["confidence"] == "APPROVED"
    assert item.to_dict()["evidence"] == ["tenant/src/coder_value_service.py:10-42"]


def test_context_package_preserves_budget_and_truncation():
    package = ContextPackage(
        task="activate coder values",
        items=[],
        budget=3,
        omitted_count=2,
        warnings=["budget_truncated"],
    )
    assert package.to_dict()["budget"] == 3
    assert package.to_dict()["omittedCount"] == 2


def test_invalid_artifact_type_is_rejected_with_structured_error():
    with pytest.raises(StructuredError) as error:
        Artifact(id="bad", artifact_type="unsupported", title="Bad")

    assert error.value.code == "INVALID_ARTIFACT_TYPE"


def test_invalid_confidence_is_rejected_with_structured_error():
    with pytest.raises(StructuredError) as error:
        ContextItem(
            id="bad",
            artifact_type="symbol",
            title="Bad",
            relevance_score=0.1,
            confidence="UNVERIFIED",
        )

    assert error.value.code == "INVALID_CONFIDENCE"


def test_evidence_free_verified_confidence_is_normalized_to_unknown():
    artifact = Artifact(
        id="symbol.without_evidence",
        artifact_type="symbol",
        title="Unproven",
        confidence="VERIFIED",
    )
    item = ContextItem(
        id="symbol.without_evidence",
        artifact_type="symbol",
        title="Unproven",
        relevance_score=0.5,
        confidence="APPROVED",
    )

    assert artifact.to_dict()["confidence"] == "UNKNOWN"
    assert item.to_dict()["confidence"] == "UNKNOWN"


def test_task_profile_rejects_unsupported_expected_artifact_type():
    with pytest.raises(StructuredError) as error:
        TaskProfile(
            id="task",
            name="Task",
            expected_artifact_types=["unsupported"],
        )

    assert error.value.code == "INVALID_ARTIFACT_TYPE"
