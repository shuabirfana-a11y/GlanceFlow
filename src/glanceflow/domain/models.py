from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from glanceflow.config import DEFAULT_TIMEZONE, NOTICE_PACKAGE_ID_PATTERN
from glanceflow.domain.enums import (
    DeadlineRole,
    NoticeType,
    TemporalNormalizationStatus,
    TemporalType,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value


class EvidenceLine(StrictModel):
    line_id: str = Field(min_length=1)
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_frame_id: str = Field(min_length=1)
    bbox: tuple[float, float, float, float] | None = None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, value: tuple[float, float, float, float] | None):
        if value is not None and (value[0] > value[2] or value[1] > value[3]):
            raise ValueError("bbox must satisfy x1 <= x2 and y1 <= y2")
        return value


class FieldEvidence(StrictModel):
    evidence_line_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class TemporalEvidenceBinding(StrictModel):
    image_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_frame_id: str = Field(min_length=1)
    evidence_line_ids: list[str] = Field(min_length=1)
    bbox: tuple[float, float, float, float]
    ocr_text: str = Field(min_length=1)
    normalized_value: str | None = None
    ocr_confidence: float = Field(ge=0.0, le=1.0)
    ocr_version: str = Field(min_length=1)
    extraction_rule_version: str = Field(min_length=1)
    safety_gate_rule_version: str = Field(min_length=1)

    @field_validator("bbox")
    @classmethod
    def valid_temporal_bbox(cls, value: tuple[float, float, float, float]):
        if value[0] > value[2] or value[1] > value[3]:
            raise ValueError("temporal bbox must satisfy x1 <= x2 and y1 <= y2")
        return value


TEMPORAL_EVIDENCE_SCHEMA_VERSION = "temporal-evidence-v1"
TEMPORAL_SAFETY_RULE_VERSION = "safety-gate-v1"


def temporal_evidence_id(
    *,
    value: datetime | None,
    temporal_type: TemporalType,
    timezone: str,
    source_text: str,
    confidence: float,
    relative_reference_time: datetime | None,
    normalization_status: TemporalNormalizationStatus,
    evidence: TemporalEvidenceBinding,
) -> str:
    payload = {
        "schema_version": TEMPORAL_EVIDENCE_SCHEMA_VERSION,
        "value": value.isoformat() if value is not None else None,
        "temporal_type": temporal_type.value,
        "timezone": timezone,
        "source_text": source_text,
        "confidence": confidence,
        "relative_reference_time": (
            relative_reference_time.isoformat()
            if relative_reference_time is not None
            else None
        ),
        "normalization_status": normalization_status.value,
        "evidence": evidence.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class TemporalField(StrictModel):
    value: datetime | None = None
    temporal_type: TemporalType
    timezone: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    relative_reference_time: datetime | None = None
    normalization_status: TemporalNormalizationStatus
    evidence: TemporalEvidenceBinding

    @field_validator("value", "relative_reference_time")
    @classmethod
    def aware_optional_datetime(cls, value: datetime | None):
        return _require_aware(value) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def valid_temporal_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def evidence_matches_temporal_value(self) -> "TemporalField":
        expected = self.value.isoformat() if self.value is not None else None
        if self.source_text != self.evidence.ocr_text:
            raise ValueError("temporal source_text must match bound OCR text")
        if self.confidence != self.evidence.ocr_confidence:
            raise ValueError("temporal confidence must match bound OCR confidence")
        if expected != self.evidence.normalized_value:
            raise ValueError("temporal value must match bound normalized value")
        if self.normalization_status is TemporalNormalizationStatus.NORMALIZED:
            if self.value is None or self.evidence.image_sha256 is None:
                raise ValueError("normalized temporal field requires value and image hash")
        if self.evidence_id != self.canonical_evidence_id():
            raise ValueError("temporal evidence_id must match the complete evidence binding")
        return self

    def canonical_evidence_id(self) -> str:
        return temporal_evidence_id(
            value=self.value,
            temporal_type=self.temporal_type,
            timezone=self.timezone,
            source_text=self.source_text,
            confidence=self.confidence,
            relative_reference_time=self.relative_reference_time,
            normalization_status=self.normalization_status,
            evidence=self.evidence,
        )

    def with_normalization_status(
        self, status: TemporalNormalizationStatus
    ) -> "TemporalField":
        payload = self.model_dump(mode="python")
        payload["normalization_status"] = status
        payload["evidence_id"] = temporal_evidence_id(
            value=self.value,
            temporal_type=self.temporal_type,
            timezone=self.timezone,
            source_text=self.source_text,
            confidence=self.confidence,
            relative_reference_time=self.relative_reference_time,
            normalization_status=status,
            evidence=self.evidence,
        )
        return TemporalField.model_validate(payload)


class MainEvent(StrictModel):
    title: str
    event_start: datetime
    location: str
    title_evidence: FieldEvidence
    time_evidence: FieldEvidence
    location_evidence: FieldEvidence
    raw_date_text: str | None = None
    raw_weekday_text: str | None = None
    unresolved_time_expression: str | None = None

    _event_start_aware = field_validator("event_start")(_require_aware)


class DeadlineAction(StrictModel):
    deadline: datetime
    action: str
    role: DeadlineRole
    deadline_evidence: FieldEvidence
    action_evidence: FieldEvidence

    _deadline_aware = field_validator("deadline")(_require_aware)


class NoticePackageDraft(StrictModel):
    notice_package_id: str = Field(pattern=NOTICE_PACKAGE_ID_PATTERN)
    notice_type: NoticeType
    captured_at: datetime
    timezone: str = DEFAULT_TIMEZONE
    source_frame_id: str = Field(min_length=1)
    main_event: MainEvent
    deadline_action: DeadlineAction | None = None
    evidence_lines: list[EvidenceLine]
    temporal_fields: list[TemporalField] = Field(default_factory=list)
    extraction_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_image_path: Path | None = Field(default=None, exclude=True, repr=False)

    _captured_at_aware = field_validator("captured_at")(_require_aware)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_unique_evidence_line_ids(self) -> "NoticePackageDraft":
        line_ids = [line.line_id for line in self.evidence_lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("evidence line_id values must be unique within a draft")
        temporal_ids = [field.evidence_id for field in self.temporal_fields]
        if len(temporal_ids) != len(set(temporal_ids)):
            raise ValueError("temporal evidence_id values must be unique within a draft")
        if any(
            field.evidence.source_frame_id != self.source_frame_id
            for field in self.temporal_fields
        ):
            raise ValueError("temporal evidence must come from the draft source frame")
        known = set(line_ids)
        if any(
            not set(field.evidence.evidence_line_ids) <= known
            for field in self.temporal_fields
        ):
            raise ValueError("temporal evidence must reference existing OCR lines")
        return self
