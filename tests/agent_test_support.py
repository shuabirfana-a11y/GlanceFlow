from datetime import datetime, timezone

from glanceflow.agent.evaluation import AgentScenario, ScenarioRuntime
from glanceflow.agent.models import AgentGoal, AgentGoalType
from glanceflow.agent.orchestrator import GlanceFlowAgent
from glanceflow.agent.registry import AgentToolRegistry


def make_agent(scenario: AgentScenario | None = None):
    runtime = ScenarioRuntime(scenario or AgentScenario("TEST-001", "test"))
    agent = GlanceFlowAgent(AgentToolRegistry.from_ports(runtime.ports()))
    goal = AgentGoal(
        goal_type=AgentGoalType.SCHEDULE_CURRENT_NOTICE,
        user_intent="安排当前通知",
        created_at=datetime.now(timezone.utc),
        session_id=f"session-{runtime.scenario.scenario_id}",
    )
    agent.start_goal(goal)
    agent.observe(goal.session_id, {"motion_state": "STATIONARY"})
    return agent, runtime, goal
