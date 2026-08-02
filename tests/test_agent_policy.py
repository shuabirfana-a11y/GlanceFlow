from glanceflow.agent.models import AgentActionType, AgentSessionState, RiskLevel
from tests.agent_test_support import make_agent


def test_policy_selects_concrete_tool_for_state():
    agent, _, goal = make_agent()
    decision = agent.decide_next_action(goal.session_id)
    assert decision.selected_action is AgentActionType.START_CAPTURE
    assert decision.tool_name == "capture_frames"
    assert decision.risk_level is RiskLevel.LOW


def test_motion_blocks_confirmed_side_effect():
    agent, _, goal = make_agent()
    session = agent._sessions[goal.session_id]
    session.observation.session_state = AgentSessionState.WAIT_CONFIRM
    session.observation.notice_draft = {"notice_package_id": "GF-PKG-1", "main_event": {}}
    agent.observe(goal.session_id, {"motion_state": "MOVING"})
    decision = agent.decide_next_action(goal.session_id)
    assert decision.selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
    assert decision.risk_level is RiskLevel.HIGH
    assert decision.tool_name is None
