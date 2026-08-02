from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from glanceflow.agent.models import AgentGoal, AgentGoalType, AgentObservation, AgentSessionState
from glanceflow.agent.state import AgentSession, AgentStateError


def test_agent_goal_is_strict_and_timezone_aware():
    goal = AgentGoal(goal_type=AgentGoalType.SCHEDULE_CURRENT_NOTICE, user_intent="安排通知", created_at=datetime.now(timezone.utc), session_id="s1")
    assert goal.goal_id.startswith("GF-GOAL-")
    with pytest.raises(ValidationError):
        AgentGoal(goal_type=AgentGoalType.SCHEDULE_CURRENT_NOTICE, user_intent="安排通知", created_at=datetime.now(), session_id="s1")


def test_observation_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AgentObservation(session_state=AgentSessionState.IDLE, timestamp=datetime.now(timezone.utc), secret="no")


def test_illegal_state_jump_is_rejected():
    goal = AgentGoal(goal_type=AgentGoalType.SCHEDULE_CURRENT_NOTICE, user_intent="安排通知", created_at=datetime.now(timezone.utc), session_id="s1")
    session = AgentSession(session_id="s1", goal=goal, observation=AgentObservation(session_state=AgentSessionState.IDLE, timestamp=datetime.now(timezone.utc)))
    with pytest.raises(AgentStateError):
        session.transition(AgentSessionState.SUCCESS)
