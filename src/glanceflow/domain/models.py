from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from glanceflow.config import DEFAULT_TIMEZONE, NOTICE_PACKAGE_ID_PATTERN
from glanceflow.domain.enums import DeadlineRole, NoticeType


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
    extraction_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

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
        return self
