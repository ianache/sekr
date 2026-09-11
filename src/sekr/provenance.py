"""Shared validation for optional provenance values."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Mapping

from sekr.errors import StructuredError


PROVENANCE_FIELDS = (
    "source", "evidence", "source_version", "content_hash",
    "observed_at", "valid_from", "valid_until",
)
_CONTENT_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


def validate_provenance(
    properties: Mapping[str, object], record: str, *, allow_legacy_null_evidence: bool = False
) -> None:
    """Validate provenance while preserving omission as the compatibility signal."""
    for field in PROVENANCE_FIELDS:
        if field not in properties:
            continue
        value = properties[field]
        if value is None and field == "evidence" and allow_legacy_null_evidence:
            continue
        if field == "evidence":
            valid_type = isinstance(value, str) or (
                isinstance(value, (list, tuple))
                and all(isinstance(reference, str) for reference in value)
            )
        else:
            valid_type = isinstance(value, str)
        if not valid_type:
            raise _invalid_provenance(field, record, "INVALID_EVIDENCE" if field == "evidence" else "INVALID_PROVENANCE")
        if field == "content_hash" and not _CONTENT_HASH.fullmatch(value):
            raise _invalid_provenance(field, record)
        if field in {"observed_at", "valid_from", "valid_until"} and not is_strict_utc_timestamp(value):
            raise _invalid_provenance(field, record)


def is_strict_utc_timestamp(value: object) -> bool:
    """Return whether *value* is a timestamp with an explicit UTC offset."""
    if not isinstance(value, str):
        return False
    if not _UTC_TIMESTAMP.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _invalid_provenance(field: str, record: str, code: str = "INVALID_PROVENANCE") -> StructuredError:
    return StructuredError(
        code,
        "Provenance field is malformed",
        {"field": field, "record": record},
    )
