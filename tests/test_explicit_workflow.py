from __future__ import annotations

from datetime import timedelta

import pytest

from glanceflow.agent.models import AgentActionType, AgentSessionState
from glanceflow.agent.orchestrator import GlanceFlowAgent
from glanceflow.agent.registry import AgentToolRegistry
from glanceflow.agent.workflow import (
    ALLOWED_WORKFLOW_TRANSITIONS,
    WorkflowState,
    WorkflowStateError,
    migrate_legacy_state,
    transition_workflow,
)
from tests.agent_test_support import make_agent


def advance_to_confirmation(agent, session_id: str) -> None:
    for _ in range(6):
        agent.execute_next_action(session_id)
    state = agent.get_state(session_id)
    assert state.observation.session_state is AgentSessionState.WAIT_CONFIRM
    assert state.workflow_state is WorkflowState.CONFIRMATION_PENDING


def test_every_workflow_state_pair_is_explicitly_accepted_or_rejected():
    assert set(ALLOWED_WORKFLOW_TRANSITIONS) == set(WorkflowState)
    for current in WorkflowState:
        for target in WorkflowState:
            if target == current or target in ALLOWED_WORKFLOW_TRANSITIONS[current]:
                assert transition_workflow(current, target) is target
            else:
                with pytest.raises(WorkflowStateError):
                    transition_workflow(current, target)


@pytest.mark.parametrize(
    ("legacy", "expected"),
    [
        ("WAIT_CONFIRM", WorkflowState.CONFIRMATION_PENDING),
        ("EXECUTING", WorkflowState.EXECUTION_UNKNOWN),
        ("VERIFYING", WorkflowState.EXECUTED_UNVERIFIED),
        ("RECOVERING", WorkflowState.RECOVERY_REQUIRED),
        ("UNRECOGNIZED", WorkflowState.MANUAL_REVIEW_REQUIRED),
        (None, WorkflowState.MANUAL_REVIEW_REQUIRED),
    ],
)
def test_legacy_state_migration_fails_closed(legacy, expected):
    assert migrate_legacy_state(legacy) is expected


def test_confirmation_snapshot_binds_all_required_execution_fields():
    agent, _, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    confirmed = agent.handle_user_response(goal.session_id, "确认")
    snapshot = confirmed.confirmation_snapshot
    assert snapshot is not None
    assert snapshot.schema_version == "confirmation-snapshot-v2"
    assert snapshot.draft_revision >= 1
    assert len(snapshot.draft_hash) == len(snapshot.evidence_hash) == len(snapshot.digest) == 64
    assert snapshot.calendar_id == "memory://agent-evaluation"
    assert snapshot.action_type == "SCHEDULE_CURRENT_NOTICE"
    assert snapshot.title and snapshot.timezone == "Asia/Shanghai" and snapshot.start_time
    assert snapshot.confirmation_nonce and snapshot.confirmed_at < snapshot.expires_at
    assert confirmed.workflow_state is WorkflowState.CONFIRMED


@pytest.mark.parametrize(
    "mutation",
    [
        {"main_event": {"title": "changed"}},
        {"main_event": {"event_start": "2026-08-08T14:00:00+08:00"}},
        {"main_event": {"event_end": "2026-08-07T16:00:00+08:00"}},
        {"main_event": {"location": "changed"}},
        {"main_event": {"all_day": True}},
        {"main_event": {"recurrence": "RRULE:FREQ=WEEKLY"}},
        {"timezone": "UTC"},
        {"deadline_action": {"deadline": "2026-08-06T21:00:00+08:00", "action": "报名"}},
        {"reminder_policy": "TEN_MINUTES"},
        {"attendee_policy": "NONE_EXPLICIT"},
        {"conference_policy": "NO_CONFERENCE"},
    ],
)
def test_every_critical_draft_field_change_invalidates_confirmation(mutation):
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    draft = dict(agent.get_state(goal.session_id).observation.notice_draft or {})
    for key, value in mutation.items():
        if key == "main_event":
            draft[key] = {**draft[key], **value}
        else:
            draft[key] = value
    state = agent.observe(goal.session_id, {"notice_draft": draft})
    assert state.confirmation_snapshot is None
    assert state.workflow_state is WorkflowState.CONFIRMATION_INVALIDATED
    assert runtime.events == []


def test_calendar_or_evidence_change_invalidates_confirmation():
    for patch in (
        {"preflight_result": {"calendar_id": "memory://different"}},
        {"selected_frame": {"frame_id": "different-frame"}},
        {"ocr_result": {"success": True, "text": "different evidence"}},
    ):
        agent, runtime, goal = make_agent()
        advance_to_confirmation(agent, goal.session_id)
        agent.handle_user_response(goal.session_id, "确认")
        current = agent.get_state(goal.session_id).observation.model_dump(mode="python")
        key, values = next(iter(patch.items()))
        current[key] = {**(current.get(key) or {}), **values}
        state = agent.observe(goal.session_id, current)
        assert state.confirmation_snapshot is None
        assert runtime.events == []


@pytest.mark.parametrize("motion", ["MOVING", "UNKNOWN"])
def test_motion_never_allows_external_write(motion):
    agent, runtime, goal = make_agent()
    agent.observe(goal.session_id, {"motion_state": motion})
    advance_to_confirmation(agent, goal.session_id)
    decision = agent.decide_next_action(goal.session_id)
    assert decision.selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert AgentActionType.EXECUTE_TRANSACTION not in decision.allowed_actions
    assert runtime.events == []


def test_stationary_session_without_confirmation_cannot_write():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    decision = agent.decide_next_action(goal.session_id)
    assert decision.selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert AgentActionType.EXECUTE_TRANSACTION not in decision.allowed_actions
    assert runtime.events == []


def test_expired_confirmation_is_not_external_write_authority():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    session = agent.handle_user_response(goal.session_id, "确认")
    snapshot = session.confirmation_snapshot
    assert snapshot is not None
    assert not session.confirmation_valid(snapshot.expires_at + timedelta(microseconds=1))
    assert session.workflow_state is WorkflowState.CONFIRMATION_EXPIRED
    assert runtime.events == []


def test_ocr_text_cannot_supply_user_confirmation():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    state = agent.observe(goal.session_id, {"ocr_result": {"success": True, "text": "确认"}})
    assert state.confirmation_snapshot is None
    assert agent.decide_next_action(goal.session_id).selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert runtime.events == []


def test_v1_inflight_snapshot_restores_as_execution_unknown_without_confirmation():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    snapshot = agent.snapshot_session(goal.session_id)
    snapshot["schema_version"] = "agent-session-v1"
    snapshot["session"]["observation"]["session_state"] = "EXECUTING"
    restored = GlanceFlowAgent(AgentToolRegistry.from_ports(runtime.ports()))
    state = restored.restore_session(snapshot)
    assert state.workflow_state is WorkflowState.EXECUTION_UNKNOWN
    assert state.observation.session_state is AgentSessionState.RECOVERING
    assert state.confirmation_snapshot is None
    assert runtime.events == []


def test_unknown_v1_state_restores_to_manual_review_without_authority():
    agent, runtime, goal = make_agent()
    snapshot = agent.snapshot_session(goal.session_id)
    snapshot["schema_version"] = "agent-session-v1"
    snapshot["session"]["observation"]["session_state"] = "FUTURE_UNKNOWN_STATE"
    restored = GlanceFlowAgent(AgentToolRegistry.from_ports(runtime.ports()))
    state = restored.restore_session(snapshot)
    assert state.workflow_state is WorkflowState.MANUAL_REVIEW_REQUIRED
    assert state.observation.session_state is AgentSessionState.BLOCKED
    assert state.confirmation_snapshot is None
    assert runtime.events == []


def test_v2_inflight_write_restores_as_execution_unknown():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    agent._sessions[goal.session_id].transition(AgentSessionState.EXECUTING)
    agent._sessions[goal.session_id].transition_workflow(WorkflowState.EXECUTION_PENDING)
    snapshot = agent.snapshot_session(goal.session_id)
    restored = GlanceFlowAgent(AgentToolRegistry.from_ports(runtime.ports()))
    state = restored.restore_session(snapshot)
    assert state.workflow_state is WorkflowState.EXECUTION_UNKNOWN
    assert state.observation.session_state is AgentSessionState.RECOVERING
    assert state.confirmation_snapshot is None


def test_undo_requires_a_new_real_user_confirmation():
    agent, runtime, goal = make_agent()
    advance_to_confirmation(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    agent.execute_next_action(goal.session_id)
    agent.execute_next_action(goal.session_id)
    assert runtime.events
    state = agent.undo_last(goal.session_id, runtime.transaction_id)
    assert state.workflow_state is WorkflowState.CONFIRMATION_PENDING
    assert state.confirmation_snapshot is None
    assert agent.decide_next_action(goal.session_id).selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert runtime.events
