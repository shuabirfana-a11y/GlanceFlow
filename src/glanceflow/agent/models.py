from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include timezone information")
    return value


class AgentGoalType(StrEnum):
    SCHEDULE_CURRENT_NOTICE = "SCHEDULE_CURRENT_NOTICE"
    CONFIRM_CURRENT_ACTION = "CONFIRM_CURRENT_ACTION"
    CANCEL_CURRENT_ACTION = "CANCEL_CURRENT_ACTION"
    UNDO_LAST_TRANSACTION = "UNDO_LAST_TRANSACTION"


class AgentSessionState(StrEnum):
    IDLE = "IDLE"
    CAPTURING = "CAPTURING"
    SELECTING_FRAME = "SELECTING_FRAME"
    READING = "READING"
    EXTRACTING = "EXTRACTING"
    VALIDATING = "VALIDATING"
    PREFLIGHTING = "PREFLIGHTING"
    NEED_INPUT = "NEED_INPUT"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    BLOCKED = "BLOCKED"
    WAIT_CONFIRM = "WAIT_CONFIRM"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    SUCCESS = "SUCCESS"
    UNDONE = "UNDONE"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class AgentActionType(StrEnum):
    START_CAPTURE = "START_CAPTURE"
    SELECT_FRAME = "SELECT_FRAME"
    RUN_OCR = "RUN_OCR"
    EXTRACT_DRAFT = "EXTRACT_DRAFT"
    RUN_SAFETY_GATE = "RUN_SAFETY_GATE"
    RUN_PREFLIGHT = "RUN_PREFLIGHT"
    ASK_USER = "ASK_USER"
    REQUEST_RECAPTURE = "REQUEST_RECAPTURE"
    WAIT_FOR_CONFIRMATION = "WAIT_FOR_CONFIRMATION"
    EXECUTE_TRANSACTION = "EXECUTE_TRANSACTION"
    VERIFY_TRANSACTION = "VERIFY_TRANSACTION"
    ROLLBACK_TRANSACTION = "ROLLBACK_TRANSACTION"
    UNDO_TRANSACTION = "UNDO_TRANSACTION"
    COMPLETE = "COMPLETE"
    BLOCK = "BLOCK"
    FAIL = "FAIL"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SideEffectLevel(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOCAL_STATE_CHANGE = "LOCAL_STATE_CHANGE"
    EXTERNAL_REVERSIBLE_ACTION = "EXTERNAL_REVERSIBLE_ACTION"


class AgentGoal(AgentModel):
    goal_id: str = Field(default_factory=lambda: f"GF-GOAL-{uuid4().hex}")
    goal_type: AgentGoalType
    user_intent: str = Field(min_length=1, max_length=200)
    created_at: datetime
    session_id: str = Field(min_length=1)
    target_notice_package_id: str | None = None
    target_transaction_id: str | None = None

    _created_at_aware = field_validator("created_at")(_aware)


class AgentObservation(AgentModel):
    session_state: AgentSessionState
    capture_result: dict[str, Any] | None = None
    selected_frame: dict[str, Any] | None = None
    ocr_result: dict[str, Any] | None = None
    notice_draft: dict[str, Any] | None = None
    safety_decision: dict[str, Any] | None = None
    preflight_result: dict[str, Any] | None = None
    user_confirmation: dict[str, Any] | None = None
    motion_state: str = "UNKNOWN"
    calendar_transaction: dict[str, Any] | None = None
    last_tool_result: dict[str, Any] | None = None
    unresolved_fields: list[str] = Field(default_factory=list)
    detected_risks: list[str] = Field(default_factory=list)
    timestamp: datetime

    _timestamp_aware = field_validator("timestamp")(_aware)


class AgentDecision(AgentModel):
    decision_id: str = Field(default_factory=lambda: f"GF-DECISION-{uuid4().hex}")
    session_id: str
    selected_action: AgentActionType
    tool_name: str | None = None
    risk_level: RiskLevel
    preconditions_met: bool
    required_inputs: list[str] = Field(default_factory=list)
    policy_rules_triggered: list[str] = Field(default_factory=list)
    rejected_actions: list[AgentActionType] = Field(default_factory=list)
    public_rationale: str = Field(min_length=1, max_length=240)
    created_at: datetime
    policy_version: str

    _created_at_aware = field_validator("created_at")(_aware)


class ToolExecutionResult(AgentModel):
    tool_call_id: str = Field(default_factory=lambda: f"GF-TOOL-{uuid4().hex}")
    tool_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None
    retryable: bool = False
    side_effect_occurred: bool = False
    started_at: datetime
    completed_at: datetime
    duration_ms: float = Field(ge=0)

    _started_at_aware = field_validator("started_at")(_aware)
    _completed_at_aware = field_validator("completed_at")(_aware)


class ConfirmationSnapshot(AgentModel):
    digest: str
    created_at: datetime
    expires_at: datetime
    risk_level: RiskLevel
    confirmation_phrase: str

    _created_at_aware = field_validator("created_at")(_aware)
    _expires_at_aware = field_validator("expires_at")(_aware)
