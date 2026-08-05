from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import Field

from glanceflow.agent.models import (
    AgentGoal,
    AgentModel,
    AgentObservation,
    AgentSessionState,
    ConfirmationSnapshot,
    RiskLevel,
)
from glanceflow.agent.workflow import WorkflowState, transition_workflow


class AgentStateError(RuntimeError):
    pass


TERMINAL_STATES = {
    AgentSessionState.SUCCESS,
    AgentSessionState.UNDONE,
    AgentSessionState.CANCELLED,
    AgentSessionState.BLOCKED,
    AgentSessionState.FAILED,
}

ALLOWED_TRANSITIONS: dict[AgentSessionState, set[AgentSessionState]] = {
    AgentSessionState.IDLE: {AgentSessionState.CAPTURING, AgentSessionState.EXECUTING, AgentSessionState.CANCELLED},
    AgentSessionState.CAPTURING: {AgentSessionState.SELECTING_FRAME, AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.SELECTING_FRAME: {AgentSessionState.READING, AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.READING: {AgentSessionState.EXTRACTING, AgentSessionState.RECOVERING, AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.EXTRACTING: {AgentSessionState.VALIDATING, AgentSessionState.NEED_INPUT, AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.BLOCKED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.VALIDATING: {AgentSessionState.PREFLIGHTING, AgentSessionState.NEED_INPUT, AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.BLOCKED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.PREFLIGHTING: {AgentSessionState.WAIT_CONFIRM, AgentSessionState.BLOCKED, AgentSessionState.RECOVERING, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.NEED_INPUT: {AgentSessionState.VALIDATING, AgentSessionState.BLOCKED, AgentSessionState.CANCELLED},
    AgentSessionState.RECAPTURE_REQUIRED: {AgentSessionState.CAPTURING, AgentSessionState.CANCELLED},
    AgentSessionState.WAIT_CONFIRM: {AgentSessionState.EXECUTING, AgentSessionState.NEED_INPUT, AgentSessionState.BLOCKED, AgentSessionState.CANCELLED},
    AgentSessionState.EXECUTING: {AgentSessionState.VERIFYING, AgentSessionState.RECOVERING, AgentSessionState.UNDONE, AgentSessionState.FAILED},
    AgentSessionState.VERIFYING: {AgentSessionState.SUCCESS, AgentSessionState.RECOVERING, AgentSessionState.FAILED},
    AgentSessionState.RECOVERING: {AgentSessionState.READING, AgentSessionState.VERIFYING, AgentSessionState.SUCCESS, AgentSessionState.BLOCKED, AgentSessionState.FAILED, AgentSessionState.CANCELLED},
    AgentSessionState.SUCCESS: {AgentSessionState.WAIT_CONFIRM, AgentSessionState.EXECUTING},
    AgentSessionState.BLOCKED: set(),
    AgentSessionState.UNDONE: set(),
    AgentSessionState.CANCELLED: set(),
    AgentSessionState.FAILED: set(),
}


RISK_RULE_VERSION = "agent-risk-v1"


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def confirmation_payload(
    observation: AgentObservation,
    risk: RiskLevel,
    *,
    draft_revision: int = 1,
    action_type: str = "SCHEDULE_CURRENT_NOTICE",
) -> dict[str, Any]:
    draft = observation.notice_draft or {}
    main = draft.get("main_event") or {}
    deadline = draft.get("deadline_action") or {}
    preflight = observation.preflight_result or {}
    evidence = {
        "selected_frame_id": (observation.selected_frame or {}).get("frame_id"),
        "ocr_result": observation.ocr_result,
        "evidence_lines": draft.get("evidence_lines") or [],
    }
    return {
        "draft_revision": draft_revision,
        "draft_hash": _digest(draft),
        "evidence_hash": _digest(evidence),
        "risk_rule_version": RISK_RULE_VERSION,
        "calendar_id": preflight.get("calendar_id") or "UNSPECIFIED",
        "action_type": action_type,
        "title": main.get("title"),
        "timezone": draft.get("timezone") or main.get("timezone") or "UNKNOWN",
        "all_day": bool(main.get("all_day", False)),
        "start_time": main.get("event_start"),
        "end_time": main.get("event_end"),
        "location": main.get("location"),
        "deadline_type": deadline.get("deadline_type") or ("EXPLICIT" if deadline else "NONE"),
        "deadline": deadline.get("deadline"),
        "reminder_policy": draft.get("reminder_policy") or "DEFAULT",
        "recurrence": main.get("recurrence"),
        "attendee_policy": draft.get("attendee_policy") or "NONE",
        "conference_policy": draft.get("conference_policy") or "NONE",
        "risk_level": risk.value,
        "has_conflict": bool((preflight.get("conflict_result") or {}).get("has_conflict")),
    }


def confirmation_digest(
    observation: AgentObservation,
    risk: RiskLevel,
    *,
    draft_revision: int = 1,
    action_type: str = "SCHEDULE_CURRENT_NOTICE",
) -> str:
    return _digest(confirmation_payload(
        observation,
        risk,
        draft_revision=draft_revision,
        action_type=action_type,
    ))


class AgentSession(AgentModel):
    session_id: str
    goal: AgentGoal
    observation: AgentObservation
    risk_level: RiskLevel = RiskLevel.LOW
    workflow_state: WorkflowState = WorkflowState.DRAFT
    draft_revision: int = Field(default=1, ge=1)
    confirmation_snapshot: ConfirmationSnapshot | None = None
    clarification_counts: dict[str, int] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    last_transaction_id: str | None = None
    tool_call_count: int = 0
    side_effect_count: int = 0
    duplicate_execution_attempts: int = 0

    def transition(self, target: AgentSessionState) -> None:
        current = self.observation.session_state
        if target == current:
            return
        if target not in ALLOWED_TRANSITIONS.get(current, set()):
            raise AgentStateError(f"illegal agent state transition: {current.value} -> {target.value}")
        self.observation.session_state = target

    def transition_workflow(self, target: WorkflowState) -> None:
        self.workflow_state = transition_workflow(self.workflow_state, target)

    def issue_confirmation(self, phrase: str, *, ttl_seconds: int = 180) -> ConfirmationSnapshot:
        if self.workflow_state is not WorkflowState.CONFIRMATION_PENDING:
            raise AgentStateError(f"workflow state {self.workflow_state.value} does not accept confirmation")
        now = datetime.now(timezone.utc)
        payload = confirmation_payload(
            self.observation,
            self.risk_level,
            draft_revision=self.draft_revision,
            action_type=self.goal.goal_type.value,
        )
        if payload["calendar_id"] == "UNSPECIFIED" or payload["timezone"] == "UNKNOWN":
            raise AgentStateError("confirmation requires an explicit calendar_id and timezone")
        snapshot = ConfirmationSnapshot(
            **payload,
            digest=_digest(payload),
            confirmed_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            confirmation_phrase=phrase,
        )
        self.confirmation_snapshot = snapshot
        self.transition_workflow(WorkflowState.CONFIRMED)
        return snapshot

    def confirmation_valid(self, now: datetime | None = None) -> bool:
        snapshot = self.confirmation_snapshot
        current = now or datetime.now(timezone.utc)
        if snapshot is None:
            return False
        if current > snapshot.expires_at:
            if self.workflow_state is WorkflowState.CONFIRMED:
                self.transition_workflow(WorkflowState.CONFIRMATION_EXPIRED)
            return False
        matches = (
            snapshot.risk_level == self.risk_level
            and snapshot.draft_revision == self.draft_revision
            and snapshot.digest == confirmation_digest(
                self.observation,
                self.risk_level,
                draft_revision=self.draft_revision,
                action_type=self.goal.goal_type.value,
            )
        )
        if not matches:
            self.invalidate_confirmation()
            return False
        return self.observation.motion_state == "STATIONARY"

    def invalidate_confirmation(self) -> None:
        self.confirmation_snapshot = None
        if self.workflow_state in {
            WorkflowState.CONFIRMATION_PENDING,
            WorkflowState.CONFIRMED,
            WorkflowState.PREFLIGHT_PENDING,
            WorkflowState.PREFLIGHT_PASSED,
            WorkflowState.EXECUTION_PENDING,
        }:
            self.transition_workflow(WorkflowState.CONFIRMATION_INVALIDATED)

    def external_write_allowed(self, *, rollback: bool = False) -> bool:
        required_state = WorkflowState.ROLLBACK_PENDING if rollback else WorkflowState.EXECUTION_PENDING
        return (
            self.workflow_state is required_state
            and (self.confirmation_snapshot is not None if rollback else self.confirmation_valid())
            and (self.last_transaction_id is not None if rollback else True)
            and self.observation.motion_state == "STATIONARY"
            and (rollback or self.risk_level is not RiskLevel.CRITICAL)
        )
