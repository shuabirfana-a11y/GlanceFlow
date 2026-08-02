from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator

from glanceflow.agent.models import AgentActionType, AgentGoalType, AgentModel, AgentSessionState, RiskLevel, ToolExecutionResult, _aware


SENSITIVE_KEYS = {"api_key", "access_token", "refresh_token", "oauth_token", "credentials", "raw_audio", "video_bytes", "chain_of_thought"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[REDACTED]" if key.lower() in SENSITIVE_KEYS else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class DecisionTraceStep(AgentModel):
    occurred_at: datetime
    current_state: AgentSessionState
    current_goal: AgentGoalType
    available_actions: list[AgentActionType]
    selected_action: AgentActionType
    policy_rules_triggered: list[str]
    risk_level: RiskLevel
    evidence_line_ids: list[str] = Field(default_factory=list)
    tool_call: str | None = None
    tool_result: dict[str, Any] | None = None
    next_state: AgentSessionState
    side_effect_occurred: bool
    verification_completed: bool
    public_rationale: str

    _occurred_at_aware = field_validator("occurred_at")(_aware)


class DecisionTrace(AgentModel):
    session_id: str
    goal_id: str
    steps: list[DecisionTraceStep] = Field(default_factory=list)

    def append(self, step: DecisionTraceStep) -> None:
        safe = step.model_copy(update={"tool_result": _redact(step.tool_result)})
        self.steps.append(safe)

    def completeness_rate(self) -> float:
        if not self.steps:
            return 0.0
        complete = sum(bool(step.policy_rules_triggered and step.public_rationale and step.next_state) for step in self.steps)
        return complete / len(self.steps)

    def write(self, json_path: Path, markdown_path: Path) -> None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(self.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        lines = ["# Agent 决策轨迹", "", f"- 会话：`{self.session_id}`", f"- 目标：`{self.goal_id}`", ""]
        for index, step in enumerate(self.steps, 1):
            lines.extend([
                f"## {index}. {step.selected_action.value}", "",
                f"- 状态：`{step.current_state.value}` → `{step.next_state.value}`",
                f"- 风险：`{step.risk_level.value}`",
                f"- 工具：`{step.tool_call or '无'}`",
                f"- 依据：{step.public_rationale}",
                f"- 副作用：{'是' if step.side_effect_occurred else '否'}；验证：{'完成' if step.verification_completed else '待完成'}", "",
            ])
        markdown_path.write_text("\n".join(lines), encoding="utf-8")


def result_for_trace(result: ToolExecutionResult | None) -> dict[str, Any] | None:
    return _redact(result.model_dump(mode="json")) if result else None
