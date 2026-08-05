from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from glanceflow.calendar.models import CalendarPreflightResult, CalendarTransactionRecord
from glanceflow.pipeline import ImagePipelineResult


class WearableModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value


class VoiceIntent(StrEnum):
    ARRANGE = "ARRANGE"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    UNDO_LAST = "UNDO_LAST"
    UNKNOWN = "UNKNOWN"


class MotionState(StrEnum):
    STATIONARY = "STATIONARY"
    MOVING = "MOVING"
    UNKNOWN = "UNKNOWN"


class SessionStatus(StrEnum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    SELECTING_FRAME = "SELECTING_FRAME"
    PROCESSING = "PROCESSING"
    WAIT_CONFIRM = "WAIT_CONFIRM"
    EXECUTING = "EXECUTING"
    SUCCESS = "SUCCESS"
    RECAPTURE = "RECAPTURE"
    NEED_INPUT = "NEED_INPUT"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VoiceTriggerEvent(WearableModel):
    raw_text: str
    normalized_text: str
    intent: VoiceIntent
    confidence: float = Field(ge=0, le=1)
    captured_at: datetime
    source: str
    session_id: str

    _captured_at_aware = field_validator("captured_at")(_aware)


class StructuredConfirmationEvent(WearableModel):
    raw_text: str
    normalized_text: str
    confidence: float = Field(ge=0, le=1)
    captured_at: datetime
    source: str
    session_id: str
    accepted_conflict: bool = False

    _captured_at_aware = field_validator("captured_at")(_aware)


class CaptureRequest(WearableModel):
    session_id: str
    video_path: Path
    output_dir: Path
    sample_interval_ms: int = Field(default=500, ge=100, le=2000)
    max_capture_ms: int = Field(default=3000, ge=500, le=5000)
    delete_source_after_processing: bool = True


class SampledFrame(WearableModel):
    frame_id: str
    timestamp_ms: int = Field(ge=0)
    image_path: Path
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    file_size_bytes: int = Field(ge=0)


class CaptureResult(WearableModel):
    session_id: str
    source_video_name: str
    sampled_frames: list[SampledFrame] = Field(default_factory=list)
    source_duration_ms: int = Field(ge=0)
    captured_duration_ms: int = Field(ge=0)
    raw_video_deleted: bool
    cancelled: bool = False
    warnings: list[str] = Field(default_factory=list)


class FrameScore(WearableModel):
    frame_id: str
    eligible: bool
    total_score: float = Field(ge=0, le=1)
    component_scores: dict[str, float]
    reasons: list[str] = Field(default_factory=list)
    ocr_line_count: int = Field(ge=0)
    ocr_character_count: int = Field(ge=0)


class FrameSelectionResult(WearableModel):
    selected_frame_id: str | None = None
    selected_image_path: Path | None = None
    scores: list[FrameScore] = Field(default_factory=list)
    requires_recapture: bool
    reason: str


class HudState(WearableModel):
    session_id: str
    status: SessionStatus
    headline: str = Field(max_length=28)
    primary_text: str = Field(max_length=96)
    secondary_text: str | None = Field(default=None, max_length=96)
    prompt: str | None = Field(default=None, max_length=72)
    severity: str
    can_confirm: bool = False
    can_cancel: bool = False
    can_undo: bool = False


class SessionAuditEvent(WearableModel):
    occurred_at: datetime
    action: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

    _occurred_at_aware = field_validator("occurred_at")(_aware)


class GlanceFlowSession(WearableModel):
    session_id: str
    status: SessionStatus = SessionStatus.IDLE
    motion_state: MotionState = MotionState.UNKNOWN
    created_at: datetime
    updated_at: datetime
    capture_result: CaptureResult | None = None
    selection_result: FrameSelectionResult | None = None
    pipeline_result: ImagePipelineResult | None = None
    preflight_result: CalendarPreflightResult | None = None
    transaction_id: str | None = None
    transaction: CalendarTransactionRecord | None = None
    conflict_confirmation_pending: bool = False
    cancellation_requested: bool = False
    last_successful_transaction_id: str | None = None
    undo_confirmation_pending: bool = False
    pending_undo_transaction_id: str | None = None
    last_voice_event: VoiceTriggerEvent | None = None
    audit_events: list[SessionAuditEvent] = Field(default_factory=list)

    _created_at_aware = field_validator("created_at")(_aware)
    _updated_at_aware = field_validator("updated_at")(_aware)
