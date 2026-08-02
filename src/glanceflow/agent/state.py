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
    AgentSessionState.SUCCESS: {AgentSessionState.EXECUTING},
    AgentSessionState.BLOCKED: set(),
    AgentSessionState.UNDONE: set(),
    AgentSessionState.CANCELLED: set(),
    AgentSessionState.FAILED: set(),
}


def confirmation_payload(observation: AgentObservation, risk: RiskLevel) -> dict[str, Any]:
    draft = observation.notice_draft or {}
    main = draft.get("main_event") or {}
    deadline = draft.get("deadline_action") or {}
    preflight = observation.preflight_result or {}
    return {
        "notice_package_id": draft.get("notice_package_id"),
        "title": main.get("title"),
        "event_start": main.get("event_start"),
        "location": main.get("location"),
        "deadline": deadline.get("deadline"),
        "risk_level": risk.value,
        "has_conflict": bool((preflight.get("conflict_result") or {}).get("has_conflict")),
        "selected_frame_id": (observation.selected_frame or {}).get("frame_id"),
    }


def confirmation_digest(observation: AgentObservation, risk: RiskLevel) -> str:
    encoded = json.dumps(confirmation_payload(observation, risk), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class AgentSession(AgentModel):
    session_id: str
    goal: AgentGoal
    observation: AgentObservation
    risk_level: RiskLevel = RiskLevel.LOW
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

    def issue_confirmation(self, phrase: str, *, ttl_seconds: int = 180) -> ConfirmationSnapshot:
        now = datetime.now(timezone.utc)
        snapshot = ConfirmationSnapshot(
            digest=confirmation_digest(self.observation, self.risk_level),
            created_at=now,
            expires_at=now + timedelta(seconds=ttl_seconds),
            risk_level=self.risk_level,
            confirmation_phrase=phrase,
        )
        self.confirmation_snapshot = snapshot
        return snapshot

    def confirmation_valid(self, now: datetime | None = None) -> bool:
        snapshot = self.confirmation_snapshot
        current = now or datetime.now(timezone.utc)
        return bool(
            snapshot
            and current <= snapshot.expires_at
            and snapshot.risk_level == self.risk_level
            and snapshot.digest == confirmation_digest(self.observation, self.risk_level)
        )

    def invalidate_confirmation(self) -> None:
        self.confirmation_snapshot = None
