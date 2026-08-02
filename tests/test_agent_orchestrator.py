import pytest

from glanceflow.agent.models import AgentActionType, AgentSessionState
from glanceflow.agent.orchestrator import AgentOrchestrationError
from tests.agent_test_support import make_agent
from glanceflow.agent.evaluation import AgentScenario


def advance_to_wait(agent, session_id):
    for _ in range(6):
        agent.execute_next_action(session_id)
    assert agent.get_state(session_id).observation.session_state is AgentSessionState.WAIT_CONFIRM


def test_normal_confirmation_execution_and_duplicate_confirmation_blocked():
    agent, runtime, goal = make_agent()
    advance_to_wait(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    assert agent.decide_next_action(goal.session_id).selected_action is AgentActionType.EXECUTE_TRANSACTION
    agent.execute_next_action(goal.session_id)
    agent.execute_next_action(goal.session_id)
    state = agent.get_state(goal.session_id)
    assert state.observation.session_state is AgentSessionState.SUCCESS
    assert runtime.events == ["main-event"]
    assert state.last_transaction_id == runtime.transaction_id
    with pytest.raises(AgentOrchestrationError):
        agent.handle_user_response(goal.session_id, "确认")


def test_confirmation_snapshot_invalidates_on_draft_change():
    agent, runtime, goal = make_agent()
    advance_to_wait(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    draft = dict(agent.get_state(goal.session_id).observation.notice_draft)
    draft["main_event"] = {**draft["main_event"], "location": "新地点"}
    agent.observe(goal.session_id, {"notice_draft": draft})
    state = agent.get_state(goal.session_id)
    assert state.confirmation_snapshot is None
    assert agent.decide_next_action(goal.session_id).selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert runtime.events == []


def test_sessions_are_isolated_and_cancelled_session_cannot_execute():
    agent, runtime, goal = make_agent()
    second = goal.model_copy(update={"goal_id": "GF-GOAL-SECOND", "session_id": "session-second"})
    agent.start_goal(second)
    with pytest.raises(AgentOrchestrationError):
        agent.observe(goal.session_id, {"session_state": "EXECUTING"})
    agent.cancel(goal.session_id)
    assert agent.get_state(goal.session_id).observation.session_state is AgentSessionState.CANCELLED
    assert agent.get_state(second.session_id).observation.session_state is AgentSessionState.IDLE
    assert runtime.events == []


def test_conflict_requires_reinforced_confirmation_phrase():
    agent, runtime, goal = make_agent(AgentScenario("CONFLICT", "conflict", conflict=True, accept_conflict=True))
    advance_to_wait(agent, goal.session_id)
    decision = agent.decide_next_action(goal.session_id)
    assert decision.selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert decision.risk_level.value == "HIGH"
    with pytest.raises(AgentOrchestrationError):
        agent.handle_user_response(goal.session_id, "确认")
    agent.handle_user_response(goal.session_id, "仍然创建")
    result = agent.execute_next_action(goal.session_id)
    assert result.tool_name == "create_calendar_transaction"
    assert result.side_effect_occurred is True
    assert runtime.events == ["main-event"]


def test_session_snapshot_restores_to_safe_state_without_confirmation():
    agent, runtime, goal = make_agent()
    advance_to_wait(agent, goal.session_id)
    agent.handle_user_response(goal.session_id, "确认")
    snapshot = agent.snapshot_session(goal.session_id)
    restored, _, _ = make_agent()
    restored._sessions.clear()
    restored._traces.clear()
    state = restored.restore_session(snapshot)
    assert state.observation.session_state is AgentSessionState.WAIT_CONFIRM
    assert state.confirmation_snapshot is None
    assert restored.decide_next_action(goal.session_id).selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert runtime.events == []
