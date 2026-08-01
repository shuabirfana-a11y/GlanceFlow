from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value


class CalendarModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EventRole(StrEnum):
    MAIN_EVENT = "MAIN_EVENT"
    DEADLINE_EVENT = "DEADLINE_EVENT"


class TransactionStatus(StrEnum):
    PLANNED = "PLANNED"
    PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CREATING = "CREATING"
    READBACK_VERIFYING = "READBACK_VERIFYING"
    VERIFIED = "VERIFIED"
    ROLLING_BACK = "ROLLING_BACK"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"
    UNDOING = "UNDOING"
    UNDONE = "UNDONE"
    CANCELLED = "CANCELLED"


class CreateEventRequest(CalendarModel):
    title: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime
    timezone: str
    location: str | None = None
    description: str
    private_metadata: dict[str, str]
    notice_package_id: str
    transaction_id: str
    event_role: EventRole

    _start_aware = field_validator("start_time")(_aware)
    _end_aware = field_validator("end_time")(_aware)

    @field_validator("end_time")
    @classmethod
    def end_after_start(cls, value: datetime, info):
        start = info.data.get("start_time")
        if start is not None and value <= start:
            raise ValueError("end_time must be after start_time")
        return value

    @model_validator(mode="after")
    def private_metadata_matches_transaction_fields(self) -> "CreateEventRequest":
        expected = {
            "notice_package_id": self.notice_package_id,
            "transaction_id": self.transaction_id,
            "event_role": self.event_role.value,
        }
        mismatches = [key for key, value in expected.items() if self.private_metadata.get(key) != value]
        if mismatches:
            raise ValueError(
                f"private_metadata must match transaction fields: {', '.join(mismatches)}"
            )
        return self


class CalendarEventSnapshot(CalendarModel):
    event_id: str
    title: str
    start_time: datetime
    end_time: datetime
    timezone: str
    location: str | None = None
    description: str
    private_metadata: dict[str, str]
    provider_name: str
    provider_updated_at: datetime | None = None

    _start_aware = field_validator("start_time")(_aware)
    _end_aware = field_validator("end_time")(_aware)

    @field_validator("provider_updated_at")
    @classmethod
    def updated_at_aware(cls, value: datetime | None):
        return _aware(value) if value is not None else None


class ConflictResult(CalendarModel):
    has_conflict: bool
    conflicting_events: list[CalendarEventSnapshot] = Field(default_factory=list)
    overlap_minutes: int = 0
    message: str


class DuplicateResult(CalendarModel):
    is_duplicate: bool
    matching_events: list[CalendarEventSnapshot] = Field(default_factory=list)
    comparison_basis: list[str] = Field(default_factory=list)
    message: str


class CalendarPreflightResult(CalendarModel):
    transaction_id: str
    passed: bool
    duplicate_result: DuplicateResult
    conflict_result: ConflictResult
    requires_conflict_confirmation: bool
    planned_requests: list[CreateEventRequest]
    messages: list[str] = Field(default_factory=list)


class UserConfirmation(CalendarModel):
    confirmed: bool
    confirmed_at: datetime
    confirmed_title: str
    confirmed_event_start: datetime
    confirmed_location: str | None = None
    confirmed_deadline: datetime | None = None
    accepted_conflict: bool = False
    confirmation_source: str

    _confirmed_at_aware = field_validator("confirmed_at")(_aware)
    _event_start_aware = field_validator("confirmed_event_start")(_aware)

    @field_validator("confirmed_deadline")
    @classmethod
    def deadline_aware(cls, value: datetime | None):
        return _aware(value) if value is not None else None


class FieldVerificationResult(CalendarModel):
    field_name: str
    passed: bool
    expected: Any
    actual: Any


class ReadbackVerificationResult(CalendarModel):
    event_id: str
    passed: bool
    field_results: list[FieldVerificationResult]
    expected_snapshot: dict[str, Any]
    actual_snapshot: dict[str, Any]
    mismatch_fields: list[str]
    message: str


class RollbackResult(CalendarModel):
    event_id: str
    delete_succeeded: bool
    absence_verified: bool
    error_message: str | None = None


class UndoResult(CalendarModel):
    event_id: str
    delete_succeeded: bool
    absence_verified: bool
    error_message: str | None = None


class AuditEvent(CalendarModel):
    occurred_at: datetime
    action: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    _occurred_at_aware = field_validator("occurred_at")(_aware)


class CalendarTransactionRecord(CalendarModel):
    transaction_id: str
    notice_package_id: str
    source_draft_snapshot: dict[str, Any]
    safety_decision_snapshot: dict[str, Any]
    preflight_result: CalendarPreflightResult | None = None
    user_confirmation: UserConfirmation | None = None
    status: TransactionStatus
    planned_requests: list[CreateEventRequest] = Field(default_factory=list)
    created_event_ids: list[str] = Field(default_factory=list)
    readback_snapshots: list[CalendarEventSnapshot] = Field(default_factory=list)
    verification_results: list[ReadbackVerificationResult] = Field(default_factory=list)
    rollback_results: list[RollbackResult] = Field(default_factory=list)
    undo_results: list[UndoResult] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    audit_events: list[AuditEvent] = Field(default_factory=list)

    _created_at_aware = field_validator("created_at")(_aware)
    _updated_at_aware = field_validator("updated_at")(_aware)
