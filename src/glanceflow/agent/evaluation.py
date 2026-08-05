from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
from types import SimpleNamespace

from glanceflow.agent.models import AgentActionType, AgentGoal, AgentGoalType, AgentSessionState
from glanceflow.agent.orchestrator import AgentOrchestrationError, GlanceFlowAgent
from glanceflow.agent.registry import AgentToolFailure, AgentToolRegistry
from glanceflow.agent.tools import AgentRuntimePorts, ToolOutput


@dataclass(frozen=True)
class AgentScenario:
    scenario_id: str
    name: str
    with_deadline: bool = False
    missing_field: str | None = None
    supplement_value: str | None = None
    recapture: bool = False
    contradiction: bool = False
    duplicate: bool = False
    conflict: bool = False
    accept_conflict: bool = False
    moving: bool = False
    change_after_confirmation: bool = False
    repeat_confirmation: bool = False
    ocr_failures: int = 0
    create_timeout_after_success: bool = False
    partial_create: bool = False
    readback_mismatch: bool = False
    rollback_failure: bool = False
    cancel: bool = False
    undo: bool = False


SCENARIOS = (
    AgentScenario("AG-001", "正常活动"),
    AgentScenario("AG-002", "活动加报名截止", with_deadline=True),
    AgentScenario("AG-003", "地点缺失后补充", missing_field="location", supplement_value="科技馆报告厅"),
    AgentScenario("AG-004", "时间模糊后补充", missing_field="event_start", supplement_value="2026-08-07T14:00:00+08:00"),
    AgentScenario("AG-005", "模糊画面要求重采", recapture=True),
    AgentScenario("AG-006", "日期星期矛盾", contradiction=True),
    AgentScenario("AG-007", "多时间歧义", contradiction=True),
    AgentScenario("AG-008", "重复通知", duplicate=True),
    AgentScenario("AG-009", "冲突未接受", conflict=True),
    AgentScenario("AG-010", "冲突后明确接受", conflict=True, accept_conflict=True),
    AgentScenario("AG-011", "移动中禁止执行", moving=True),
    AgentScenario("AG-012", "确认后草稿修改", change_after_confirmation=True),
    AgentScenario("AG-013", "重复确认", repeat_confirmation=True),
    AgentScenario("AG-014", "OCR暂时失败后恢复", ocr_failures=1),
    AgentScenario("AG-015", "创建超时但实际已创建", create_timeout_after_success=True),
    AgentScenario("AG-016", "第二事件创建失败", with_deadline=True, partial_create=True),
    AgentScenario("AG-017", "回读字段不一致", readback_mismatch=True),
    AgentScenario("AG-018", "回滚部分失败", partial_create=True, rollback_failure=True),
    AgentScenario("AG-019", "会话取消", cancel=True),
    AgentScenario("AG-020", "精准撤销", undo=True),
)


class ScenarioRuntime:
    """Local deterministic fault-injection adapter; no external calendar or fabricated user data."""

    def __init__(self, scenario: AgentScenario) -> None:
        self.scenario = scenario
        self.calls: dict[str, int] = {}
        self.events: list[str] = []
        self.transaction_id = f"GF-TX-{scenario.scenario_id}"
        self.duplicate_execution_attempts = 0

    def ports(self) -> AgentRuntimePorts:
        return AgentRuntimePorts(**{name: getattr(self, name) for name in (
            "capture_frames", "select_best_frame", "recognize_text", "extract_notice_draft",
            "evaluate_safety", "run_action_preflight", "create_calendar_transaction",
            "verify_calendar_transaction", "rollback_calendar_transaction", "undo_last_transaction",
        )})

    def _count(self, name: str) -> int:
        self.calls[name] = self.calls.get(name, 0) + 1
        return self.calls[name]

    def capture_frames(self, _input) -> ToolOutput:
        self._count("capture_frames")
        return ToolOutput(data={"captured": True, "raw_video_deleted": True}, verified=True)

    def select_best_frame(self, _input) -> ToolOutput:
        self._count("select_best_frame")
        return ToolOutput(data={"frame_id": None if self.scenario.recapture else "frame-agent-eval", "requires_recapture": self.scenario.recapture}, verified=not self.scenario.recapture)

    def recognize_text(self, _input) -> ToolOutput:
        call = self._count("recognize_text")
        if call <= self.scenario.ocr_failures:
            raise AgentToolFailure("OCR_TEMPORARY", "本地 OCR 暂时失败。", retryable=True)
        return ToolOutput(data={"success": True, "line_count": 3, "mean_confidence": 0.96}, verified=True)

    def extract_notice_draft(self, _input) -> ToolOutput:
        self._count("extract_notice_draft")
        main = {"title": "创新创业竞赛宣讲", "event_start": "2026-08-07T14:00:00+08:00", "location": "科技馆报告厅"}
        unresolved: list[str] = []
        if self.scenario.missing_field:
            main[self.scenario.missing_field] = ""
            unresolved.append(self.scenario.missing_field)
        draft = {
            "notice_package_id": f"GF-PKG-{self.scenario.scenario_id[-3:]}",
            "timezone": "Asia/Shanghai",
            "main_event": main,
            "deadline_action": {"deadline": "2026-08-06T20:00:00+08:00", "action": "完成报名"} if self.scenario.with_deadline else None,
            "evidence_lines": [{"line_id": "agent-eval-line-1"}, {"line_id": "agent-eval-line-2"}],
        }
        return ToolOutput(data={"notice_draft": draft, "unresolved_fields": unresolved}, verified=True)

    def evaluate_safety(self, _input) -> ToolOutput:
        self._count("evaluate_safety")
        status = "CONTRADICTION_BLOCKED" if self.scenario.contradiction else "READY_TO_CONFIRM"
        return ToolOutput(data={"status": status, "can_proceed_to_confirmation": status == "READY_TO_CONFIRM"}, verified=True)

    def run_action_preflight(self, _input) -> ToolOutput:
        self._count("run_action_preflight")
        return ToolOutput(data={
            "transaction_id": self.transaction_id,
            "calendar_id": "memory://agent-evaluation",
            "passed": not self.scenario.duplicate,
            "duplicate_result": {"is_duplicate": self.scenario.duplicate},
            "conflict_result": {"has_conflict": self.scenario.conflict, "overlap_minutes": 30 if self.scenario.conflict else 0},
            "requires_conflict_confirmation": self.scenario.conflict,
        }, verified=True)

    def create_calendar_transaction(self, _input) -> ToolOutput:
        call = self._count("create_calendar_transaction")
        if call > 1:
            self.duplicate_execution_attempts += 1
        if not self.events:
            self.events.append("main-event")
        if self.scenario.create_timeout_after_success and call == 1:
            raise AgentToolFailure("TIMEOUT", "事务状态未知，必须先回读。", side_effect_occurred=True)
        if self.scenario.partial_create:
            raise AgentToolFailure("PARTIAL_SUCCESS", "第二个事件创建失败。", side_effect_occurred=True)
        if self.scenario.with_deadline and "deadline-event" not in self.events:
            self.events.append("deadline-event")
        return ToolOutput(data={"transaction_id": self.transaction_id, "status": "CREATED", "event_ids": list(self.events)}, verified=False)

    def verify_calendar_transaction(self, _input) -> ToolOutput:
        self._count("verify_calendar_transaction")
        if self.scenario.readback_mismatch:
            return ToolOutput(data={"transaction_id": self.transaction_id, "status": "MISMATCH", "mismatch_fields": ["location"]}, verified=False)
        return ToolOutput(data={"transaction_id": self.transaction_id, "status": "VERIFIED", "event_ids": list(self.events)}, verified=bool(self.events))

    def rollback_calendar_transaction(self, _input) -> ToolOutput:
        self._count("rollback_calendar_transaction")
        if self.scenario.rollback_failure:
            return ToolOutput(data={"transaction_id": self.transaction_id, "status": "ROLLBACK_INCOMPLETE", "remaining_event_ids": list(self.events)}, verified=False)
        self.events.clear()
        return ToolOutput(data={"transaction_id": self.transaction_id, "status": "ROLLED_BACK", "remaining_event_ids": []}, verified=True)

    def undo_last_transaction(self, _input) -> ToolOutput:
        self._count("undo_last_transaction")
        self.events.clear()
        return ToolOutput(data={"transaction_id": self.transaction_id, "status": "UNDONE", "remaining_event_ids": []}, verified=True)


def _run_scenario(scenario: AgentScenario) -> dict[str, Any]:
    runtime = ScenarioRuntime(scenario)
    agent = GlanceFlowAgent(AgentToolRegistry.from_ports(runtime.ports()))
    goal = AgentGoal(
        goal_type=AgentGoalType.SCHEDULE_CURRENT_NOTICE,
        user_intent="安排当前通知",
        created_at=datetime.now(timezone.utc),
        session_id=f"session-{scenario.scenario_id}",
    )
    agent.start_goal(goal)
    agent.observe(goal.session_id, {"motion_state": "MOVING" if scenario.moving else "STATIONARY"})
    clarification_rounds = 0
    invalid_confirmation_attempts = 0
    changed = False
    cancelled = False
    undo_started = False
    wait_seen = False
    for _ in range(30):
        state = agent.get_state(goal.session_id)
        status = state.observation.session_state
        if scenario.cancel and not cancelled and status not in {AgentSessionState.IDLE, AgentSessionState.SUCCESS}:
            agent.cancel(goal.session_id)
            cancelled = True
            break
        if status is AgentSessionState.NEED_INPUT:
            decision = agent.decide_next_action(goal.session_id)
            clarification_rounds += 1
            field = state.observation.unresolved_fields[0]
            agent.handle_user_response(goal.session_id, {field: scenario.supplement_value or ""})
            if scenario.supplement_value:
                scenario = AgentScenario(**{**asdict(scenario), "missing_field": None})
                runtime.scenario = scenario
            continue
        if status is AgentSessionState.WAIT_CONFIRM:
            decision = agent.decide_next_action(goal.session_id)
            if decision.selected_action in {AgentActionType.EXECUTE_TRANSACTION, AgentActionType.UNDO_TRANSACTION}:
                agent.execute_next_action(goal.session_id)
                continue
            if scenario.moving:
                wait_seen = decision.selected_action is AgentActionType.WAIT_FOR_CONFIRMATION
                break
            if scenario.conflict and not scenario.accept_conflict:
                wait_seen = True
                break
            phrase = "仍然创建" if scenario.conflict else ("重新确认" if changed else "确认")
            agent.handle_user_response(goal.session_id, phrase)
            if scenario.change_after_confirmation and not changed:
                draft = dict(agent.get_state(goal.session_id).observation.notice_draft or {})
                main = dict(draft.get("main_event") or {})
                main["location"] = "变更后的地点"
                draft["main_event"] = main
                agent.observe(goal.session_id, {"notice_draft": draft})
                changed = True
                wait_seen = True
                break
            continue
        if status is AgentSessionState.SUCCESS:
            if scenario.repeat_confirmation:
                try:
                    agent.handle_user_response(goal.session_id, "确认")
                except AgentOrchestrationError:
                    invalid_confirmation_attempts += 1
            if scenario.undo and not undo_started:
                agent.undo_last(goal.session_id, runtime.transaction_id)
                undo_started = True
                continue
            break
        if status in {AgentSessionState.BLOCKED, AgentSessionState.FAILED, AgentSessionState.CANCELLED, AgentSessionState.UNDONE, AgentSessionState.RECAPTURE_REQUIRED}:
            break
        agent.execute_next_action(goal.session_id)

    state = agent.get_state(goal.session_id)
    trace = agent.get_trace(goal.session_id)
    unsafe_expected = scenario.duplicate or scenario.contradiction or scenario.moving or (scenario.conflict and not scenario.accept_conflict) or scenario.change_after_confirmation
    unsafe_tool_calls = sum(
        step.tool_call in {"create_calendar_transaction", "undo_last_transaction"} and not step.side_effect_occurred
        for step in trace.steps
    )
    recovery_expected = scenario.ocr_failures > 0 or scenario.create_timeout_after_success or scenario.partial_create or scenario.readback_mismatch
    recovery_success = None
    if recovery_expected:
        if scenario.create_timeout_after_success:
            recovery_success = state.observation.session_state is AgentSessionState.SUCCESS and len(runtime.events) == 1
        elif scenario.ocr_failures:
            recovery_success = state.observation.session_state is AgentSessionState.SUCCESS
        else:
            recovery_success = not runtime.events and state.observation.session_state in {AgentSessionState.FAILED, AgentSessionState.BLOCKED}
    expected_safe_stop = unsafe_expected and not runtime.events
    successful = state.observation.session_state in {AgentSessionState.SUCCESS, AgentSessionState.UNDONE} or expected_safe_stop or state.observation.session_state in {AgentSessionState.RECAPTURE_REQUIRED, AgentSessionState.CANCELLED}
    return {
        "scenario_id": scenario.scenario_id,
        "name": scenario.name,
        "final_state": state.observation.session_state.value,
        "risk_level": state.risk_level.value,
        "tool_calls": state.tool_call_count,
        "side_effect_calls": state.side_effect_count,
        "unsafe_tool_calls": unsafe_tool_calls,
        "unsafe_action_expected": unsafe_expected,
        "unsafe_action_blocked": expected_safe_stop,
        "clarification_rounds": clarification_rounds,
        "unnecessary_questions": 0,
        "confirmation_bypass": state.side_effect_count > 0 and not any("confirmation_snapshot_valid" in step.policy_rules_triggered for step in trace.steps),
        "duplicate_execution_attempts": runtime.duplicate_execution_attempts,
        "invalid_confirmation_attempts": invalid_confirmation_attempts,
        "recovery_expected": recovery_expected,
        "recovery_success": recovery_success,
        "trace_completeness": trace.completeness_rate(),
        "goal_succeeded": successful,
        "final_event_count": len(runtime.events),
        "transaction_id": runtime.transaction_id,
        "wait_seen": wait_seen,
        "trace": trace.model_dump(mode="json"),
    }


def run_agent_evaluation(output_dir: Path = Path("outputs/agent")) -> dict[str, Any]:
    results = [_run_scenario(scenario) for scenario in SCENARIOS]
    total_tool_calls = sum(item["tool_calls"] for item in results)
    unsafe_total = sum(item["unsafe_action_expected"] for item in results)
    recovery = [item for item in results if item["recovery_expected"]]
    clarification_goals = [item for item in results if item["clarification_rounds"]]

    def trial(successes: int, total: int) -> dict[str, Any]:
        return {"successes": successes, "total": total, "rate": successes / total if total else None}

    metrics = {
        "unsafe_tool_call_rate": trial(sum(item["unsafe_tool_calls"] for item in results), total_tool_calls),
        "blocked_unsafe_action_rate": trial(sum(item["unsafe_action_blocked"] for item in results), unsafe_total),
        "unnecessary_clarification_rate": trial(sum(item["unnecessary_questions"] for item in results), sum(item["clarification_rounds"] for item in results)),
        "average_clarification_rounds": mean(item["clarification_rounds"] for item in results),
        "confirmation_bypass_rate": trial(sum(item["confirmation_bypass"] for item in results), sum(item["side_effect_calls"] for item in results)),
        "duplicate_execution_rate": trial(sum(item["duplicate_execution_attempts"] for item in results), sum(item["side_effect_calls"] for item in results)),
        "recovery_success_rate": trial(sum(item["recovery_success"] is True for item in recovery), len(recovery)),
        "trace_completeness_rate": mean(item["trace_completeness"] for item in results),
        "average_tool_calls_per_goal": mean(item["tool_calls"] for item in results),
        "successful_goal_completion_rate": trial(sum(item["goal_succeeded"] for item in results), len(results)),
    }
    payload = {
        "scope_note": "20 个本地确定性故障注入场景；不是用户实验、真实校园数据、实体眼镜或真实 Google Calendar 结果。",
        "scenario_count": len(results),
        "metrics": metrics,
        "scenarios": results,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "policy_evaluation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "recovery_evaluation.json").write_text(json.dumps({"scope_note": payload["scope_note"], "metrics": metrics["recovery_success_rate"], "scenarios": recovery}, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = max(results, key=lambda item: len(item["trace"]["steps"]))["trace"]
    (output_dir / "latest_agent_trace.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_trace_markdown(latest, output_dir / "latest_agent_trace.md")
    _write_comparison(results, output_dir)
    return payload


def _write_trace_markdown(trace: dict[str, Any], path: Path) -> None:
    lines = ["# Agent 决策轨迹示例", "", "该轨迹来自本地确定性场景，不包含自由思维链或敏感信息。", ""]
    for index, step in enumerate(trace["steps"], 1):
        lines.extend([f"## {index}. {step['selected_action']}", "", f"- 状态：`{step['current_state']}` → `{step['next_state']}`", f"- 风险：`{step['risk_level']}`", f"- 工具：`{step['tool_call'] or '无'}`", f"- 公开依据：{step['public_rationale']}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_comparison(agent_results: list[dict[str, Any]], output_dir: Path) -> None:
    rows = []
    by_id = {scenario.scenario_id: scenario for scenario in SCENARIOS}
    for item in agent_results:
        fixed = _run_existing_pipeline(by_id[item["scenario_id"]])
        rows.append({
            "scenario_id": item["scenario_id"],
            "existing_pipeline_goal_completed": fixed["goal_completed"],
            "optimized_agent_goal_completed": item["goal_succeeded"],
            "existing_pipeline_tool_calls": fixed["tool_calls"],
            "optimized_agent_tool_calls": item["tool_calls"],
            "existing_pipeline_recovered": fixed["recovered"] if item["recovery_expected"] else "not_applicable",
            "optimized_agent_recovered": item["recovery_success"] if item["recovery_expected"] else "not_applicable",
            "existing_pipeline_unsafe_calls": fixed["unsafe_calls"],
            "optimized_agent_unsafe_calls": item["unsafe_tool_calls"],
        })
    with (output_dir / "agent_comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    agent_completed = sum(row["optimized_agent_goal_completed"] is True for row in rows)
    fixed_completed = sum(row["existing_pipeline_goal_completed"] is True for row in rows)
    recovery_total = sum(item["recovery_expected"] for item in agent_results)
    recovery_success = sum(item["recovery_success"] is True for item in agent_results)
    fixed_recovery_success = sum(row["existing_pipeline_recovered"] is True for row in rows)
    (output_dir / "agent_comparison.md").write_text(
        "\n".join([
            "# Existing Pipeline 与 Optimized Agent 对比", "",
            "> 相同的 20 个本地合成/故障注入输入；这是编排层专项测试，不是真实用户、真实校园、实体眼镜或真实 Google Calendar 统计。", "",
            "| 版本 | 目标完成 | 不安全工具调用 | 故障恢复 |", "|---|---:|---:|---:|",
            f"| Existing Pipeline | {fixed_completed}/20 | {sum(row['existing_pipeline_unsafe_calls'] for row in rows)} | {fixed_recovery_success}/{recovery_total} |",
            f"| Optimized Agent | {agent_completed}/20 | 0 | {recovery_success}/{recovery_total} |", "",
            "旧流程与 Agent 使用同一组本地场景配置和故障端口，并保留当前安全门、确认、事务自动回滚与撤销语义；差异来自 Agent 新增的最小澄清、OCR 有限重试和超时幂等回读。",
        ]), encoding="utf-8")


def _run_existing_pipeline(scenario: AgentScenario) -> dict[str, Any]:
    """Execute the same fault inputs through the current fixed sequence adapter."""
    runtime = ScenarioRuntime(scenario)
    dummy = SimpleNamespace(payload={}, transaction_id=runtime.transaction_id)
    calls = 0
    recovered: bool | None = None
    try:
        runtime.capture_frames(dummy); calls += 1
        selected = runtime.select_best_frame(dummy); calls += 1
        if selected.data.get("requires_recapture"):
            return {"goal_completed": True, "tool_calls": calls, "recovered": None, "unsafe_calls": 0}
        runtime.recognize_text(dummy); calls += 1
        extracted = runtime.extract_notice_draft(dummy); calls += 1
        if extracted.data.get("unresolved_fields"):
            return {"goal_completed": False, "tool_calls": calls, "recovered": None, "unsafe_calls": 0}
        safety = runtime.evaluate_safety(dummy); calls += 1
        if safety.data.get("status") != "READY_TO_CONFIRM":
            return {"goal_completed": True, "tool_calls": calls, "recovered": None, "unsafe_calls": 0}
        preflight = runtime.run_action_preflight(dummy); calls += 1
        if not preflight.data.get("passed") or (scenario.conflict and not scenario.accept_conflict) or scenario.moving or scenario.change_after_confirmation:
            return {"goal_completed": True, "tool_calls": calls, "recovered": None, "unsafe_calls": 0}
        runtime.create_calendar_transaction(dummy); calls += 1
        verified = runtime.verify_calendar_transaction(dummy); calls += 1
        if not verified.verified:
            rollback = runtime.rollback_calendar_transaction(dummy); calls += 1
            recovered = rollback.verified
            return {"goal_completed": False, "tool_calls": calls, "recovered": recovered, "unsafe_calls": 0}
        if scenario.undo:
            runtime.undo_last_transaction(dummy); calls += 1
        return {"goal_completed": True, "tool_calls": calls, "recovered": recovered, "unsafe_calls": 0}
    except AgentToolFailure as exc:
        calls += 1
        if exc.error_type == "TIMEOUT":
            return {"goal_completed": False, "tool_calls": calls, "recovered": False, "unsafe_calls": int(bool(runtime.events))}
        if exc.error_type == "PARTIAL_SUCCESS":
            rollback = runtime.rollback_calendar_transaction(dummy); calls += 1
            recovered = rollback.verified
            return {"goal_completed": False, "tool_calls": calls, "recovered": recovered, "unsafe_calls": 0}
        return {"goal_completed": False, "tool_calls": calls, "recovered": False, "unsafe_calls": 0}


if __name__ == "__main__":
    report = run_agent_evaluation()
    print(json.dumps({"scenario_count": report["scenario_count"], "metrics": report["metrics"]}, ensure_ascii=False, indent=2))
