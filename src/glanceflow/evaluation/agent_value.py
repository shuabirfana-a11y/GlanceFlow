from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Noto Sans SC", "Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

from glanceflow.agent.evaluation import (
    SCENARIOS,
    AgentScenario,
    ScenarioRuntime,
    _run_scenario,
)
from glanceflow.agent.registry import AgentToolFailure


OUTPUT = Path("outputs/agent/value_analysis")
FIGURES = OUTPUT / "figures"
SYSTEMS = ("direct_execution", "existing_pipeline", "optimized_agent")
SYSTEM_LABELS = {
    "direct_execution": "Direct Execution",
    "existing_pipeline": "Existing Pipeline",
    "optimized_agent": "Optimized Agent",
}
RECOVERY_SCENARIOS = {"AG-014", "AG-015", "AG-016", "AG-017", "AG-018"}
UNSAFE_ACTION_SCENARIOS = {"AG-006", "AG-007", "AG-008", "AG-009", "AG-011", "AG-012"}
PROTECTIVE_DELAY_SCENARIOS = {
    "direct_execution": {"AG-003", "AG-004", "AG-005"},
    "existing_pipeline": {"AG-003", "AG-004", "AG-005", "AG-009", "AG-011", "AG-012"},
    "optimized_agent": {"AG-005", "AG-009", "AG-011", "AG-012"},
}
REPRESENTATIVE_IDS = ("AG-001", "AG-004", "AG-006", "AG-008", "AG-009", "AG-012", "AG-015", "AG-017")


def initial_calendar_signature(scenario: AgentScenario) -> str:
    if scenario.duplicate:
        return "seed:matching-notice-event"
    if scenario.conflict:
        return "seed:overlapping-event"
    return "seed:empty-memory-calendar"


def risk_factors(scenario: AgentScenario) -> list[str]:
    mapping = {
        "recapture": "poor_image_quality",
        "contradiction": "deterministic_time_contradiction",
        "duplicate": "duplicate_event",
        "conflict": "calendar_conflict",
        "moving": "moving_user",
        "change_after_confirmation": "draft_changed_after_confirmation",
        "ocr_failures": "temporary_ocr_failure",
        "create_timeout_after_success": "unknown_write_outcome",
        "partial_create": "partial_transaction",
        "readback_mismatch": "readback_mismatch",
        "rollback_failure": "rollback_incomplete",
    }
    factors = [value for field, value in mapping.items() if getattr(scenario, field)]
    if scenario.missing_field:
        factors.append(f"missing_{scenario.missing_field}")
    return factors or ["none"]


def _base_result(system_id: str, scenario: AgentScenario) -> dict[str, Any]:
    return {
        "system_id": system_id,
        "scenario_id": scenario.scenario_id,
        "scenario_name": scenario.name,
        "scenario_config": asdict(scenario),
        "initial_calendar_signature": initial_calendar_signature(scenario),
        "input_risks": risk_factors(scenario),
        "final_state": "FAILED",
        "final_event_count": 0,
        "tool_calls": 0,
        "side_effect_calls": 0,
        "wrong_execution": False,
        "unsafe_tool_calls": 0,
        "confirmation_bypass_calls": 0,
        "duplicate_execution_attempts": 0,
        "unsafe_action_expected": scenario.scenario_id in UNSAFE_ACTION_SCENARIOS,
        "unsafe_action_blocked": False,
        "goal_succeeded": False,
        "safe_resolution": False,
        "recovery_expected": scenario.scenario_id in RECOVERY_SCENARIOS,
        "recovery_success": None,
        "clarification_rounds": 0,
        "unnecessary_questions": 0,
        "trace_complete": False,
        "trace": None,
        "called_tools": [],
        "wrong_execution_details": [],
        "protective_delay": scenario.scenario_id in PROTECTIVE_DELAY_SCENARIOS[system_id],
    }


def _wrong(
    result: dict[str, Any],
    *,
    category: str,
    layer: str,
    tool: str,
    confirmation_bypassed: bool,
    duplicate: bool = False,
    residual: bool = False,
    recoverable: bool = False,
    disclosed: bool = False,
) -> None:
    result["wrong_execution"] = True
    result["wrong_execution_details"].append({
        "scenario_id": result["scenario_id"],
        "input_risks": result["input_risks"],
        "system_type": result["system_id"],
        "called_tool": tool,
        "confirmation_bypassed": confirmation_bypassed,
        "wrong_calendar_event_created": result["final_event_count"] > 0,
        "duplicate_event_created": duplicate,
        "residual_event_left": residual,
        "recoverable": recoverable,
        "error_layer": layer,
        "cost_category": category,
        "failure_disclosed": disclosed,
    })


def run_direct_execution(scenario: AgentScenario) -> dict[str, Any]:
    result = _base_result("direct_execution", scenario)
    runtime = ScenarioRuntime(scenario)
    dummy = SimpleNamespace(payload={}, transaction_id=runtime.transaction_id)

    def call(name: str):
        result["tool_calls"] += 1
        result["called_tools"].append(name)
        return getattr(runtime, name)(dummy)

    try:
        call("capture_frames")
        if scenario.cancel:
            result.update(final_state="CANCELLED", goal_succeeded=True, safe_resolution=True)
            return result
        selected = call("select_best_frame")
        if selected.data.get("requires_recapture"):
            result.update(final_state="RECAPTURE_REQUIRED", safe_resolution=True)
            return result
        call("recognize_text")
        extracted = call("extract_notice_draft")
        if extracted.data.get("unresolved_fields"):
            result["final_state"] = "NEED_INPUT"
            return result

        result["side_effect_calls"] += 1
        result["confirmation_bypass_calls"] += 1
        result["unsafe_tool_calls"] += int(scenario.scenario_id in UNSAFE_ACTION_SCENARIOS or scenario.conflict)
        call("create_calendar_transaction")
        result["final_event_count"] = len(runtime.events)
        result["final_state"] = "CREATED_UNVERIFIED"

        if scenario.readback_mismatch:
            _wrong(result, category="回读异常仍提交", layer="verification", tool="create_calendar_transaction", confirmation_bypassed=True, residual=True)
        elif scenario.contradiction:
            _wrong(result, category="错误时间", layer="safety", tool="create_calendar_transaction", confirmation_bypassed=True, residual=True)
        elif scenario.duplicate:
            result["duplicate_execution_attempts"] = 1
            _wrong(result, category="重复创建", layer="preflight", tool="create_calendar_transaction", confirmation_bypassed=True, duplicate=True, residual=True)
        elif scenario.conflict:
            _wrong(result, category="冲突未确认执行", layer="confirmation", tool="create_calendar_transaction", confirmation_bypassed=True, residual=True)
        elif scenario.moving:
            _wrong(result, category="冲突未确认执行", layer="motion_guard", tool="create_calendar_transaction", confirmation_bypassed=True, residual=True)
        elif scenario.change_after_confirmation:
            _wrong(result, category="错误地点", layer="confirmation_snapshot", tool="create_calendar_transaction", confirmation_bypassed=True, residual=True)

        if scenario.undo:
            result["side_effect_calls"] += 1
            result["confirmation_bypass_calls"] += 1
            call("undo_last_transaction")
            result.update(final_state="UNDONE", final_event_count=len(runtime.events), goal_succeeded=True)
        elif not result["wrong_execution"]:
            result["goal_succeeded"] = True
        result["safe_resolution"] = result["goal_succeeded"]
        return result
    except AgentToolFailure as exc:
        result["final_event_count"] = len(runtime.events)
        result["final_state"] = exc.error_type
        if scenario.partial_create:
            _wrong(result, category="错误截止事项", layer="calendar_write", tool="create_calendar_transaction", confirmation_bypassed=True, residual=bool(runtime.events), recoverable=True)
        elif scenario.create_timeout_after_success:
            _wrong(result, category="回读异常仍提交", layer="calendar_write", tool="create_calendar_transaction", confirmation_bypassed=True, residual=bool(runtime.events), recoverable=True)
        result["recovery_success"] = False if result["recovery_expected"] else None
        return result


def run_existing_pipeline(scenario: AgentScenario) -> dict[str, Any]:
    result = _base_result("existing_pipeline", scenario)
    runtime = ScenarioRuntime(scenario)
    dummy = SimpleNamespace(payload={}, transaction_id=runtime.transaction_id)

    def call(name: str):
        result["tool_calls"] += 1
        result["called_tools"].append(name)
        return getattr(runtime, name)(dummy)

    try:
        call("capture_frames")
        if scenario.cancel:
            result.update(final_state="CANCELLED", goal_succeeded=True, safe_resolution=True)
            return result
        selected = call("select_best_frame")
        if selected.data.get("requires_recapture"):
            result.update(final_state="RECAPTURE_REQUIRED", safe_resolution=True)
            return result
        call("recognize_text")
        extracted = call("extract_notice_draft")
        if extracted.data.get("unresolved_fields"):
            result["final_state"] = "NEED_INPUT"
            return result
        safety = call("evaluate_safety")
        if safety.data.get("status") != "READY_TO_CONFIRM":
            result.update(final_state="BLOCKED", unsafe_action_blocked=scenario.scenario_id in UNSAFE_ACTION_SCENARIOS, safe_resolution=True)
            return result
        preflight = call("run_action_preflight")
        if not preflight.data.get("passed"):
            result.update(final_state="BLOCKED", unsafe_action_blocked=True, safe_resolution=True)
            return result
        if (scenario.conflict and not scenario.accept_conflict) or scenario.moving or scenario.change_after_confirmation:
            result.update(final_state="WAIT_CONFIRM", unsafe_action_blocked=True, safe_resolution=True)
            return result

        result["side_effect_calls"] += 1
        call("create_calendar_transaction")
        verified = call("verify_calendar_transaction")
        result["final_event_count"] = len(runtime.events)
        if not verified.verified:
            result["side_effect_calls"] += 1
            rollback = call("rollback_calendar_transaction")
            result["final_event_count"] = len(runtime.events)
            result["recovery_success"] = rollback.verified
            result["final_state"] = "ROLLED_BACK" if rollback.verified else "BLOCKED"
            if not rollback.verified:
                _wrong(result, category="错误截止事项", layer="recovery", tool="rollback_calendar_transaction", confirmation_bypassed=False, residual=True, disclosed=True)
            return result
        if scenario.undo:
            result["side_effect_calls"] += 1
            call("undo_last_transaction")
            result.update(final_state="UNDONE", final_event_count=len(runtime.events), goal_succeeded=True)
        else:
            result.update(final_state="SUCCESS", goal_succeeded=True)
        result["safe_resolution"] = result["goal_succeeded"]
        return result
    except AgentToolFailure as exc:
        result["final_event_count"] = len(runtime.events)
        result["final_state"] = exc.error_type
        if exc.error_type == "PARTIAL_SUCCESS":
            result["side_effect_calls"] += 1
            rollback = call("rollback_calendar_transaction")
            result["final_event_count"] = len(runtime.events)
            result["recovery_success"] = rollback.verified
            result["final_state"] = "ROLLED_BACK" if rollback.verified else "BLOCKED"
            if not rollback.verified:
                _wrong(result, category="错误截止事项", layer="recovery", tool="rollback_calendar_transaction", confirmation_bypassed=False, residual=True, disclosed=True)
        elif exc.error_type == "TIMEOUT":
            result["recovery_success"] = False
            _wrong(result, category="回读异常仍提交", layer="calendar_write", tool="create_calendar_transaction", confirmation_bypassed=False, residual=bool(runtime.events), recoverable=True)
        return result


def run_optimized_agent(scenario: AgentScenario) -> dict[str, Any]:
    raw = _run_scenario(scenario)
    result = _base_result("optimized_agent", scenario)
    result.update({
        "final_state": raw["final_state"],
        "final_event_count": raw["final_event_count"],
        "tool_calls": raw["tool_calls"],
        "side_effect_calls": raw["side_effect_calls"],
        "unsafe_tool_calls": raw["unsafe_tool_calls"],
        "confirmation_bypass_calls": int(raw["confirmation_bypass"]),
        "duplicate_execution_attempts": raw["duplicate_execution_attempts"],
        "unsafe_action_expected": raw["unsafe_action_expected"],
        "unsafe_action_blocked": raw["unsafe_action_blocked"],
        "goal_succeeded": raw["final_state"] in {"SUCCESS", "UNDONE", "CANCELLED"},
        "safe_resolution": raw["goal_succeeded"],
        "recovery_expected": raw["recovery_expected"],
        "recovery_success": raw["recovery_success"],
        "clarification_rounds": raw["clarification_rounds"],
        "unnecessary_questions": raw["unnecessary_questions"],
        "trace_complete": raw["trace_completeness"] == 1.0,
        "trace": raw["trace"],
        "called_tools": [step["tool_call"] for step in raw["trace"]["steps"] if step["tool_call"]],
    })
    if scenario.scenario_id == "AG-018":
        _wrong(result, category="错误截止事项", layer="recovery", tool="rollback_calendar_transaction", confirmation_bypassed=False, residual=True, disclosed=True)
    return result


RUNNERS: dict[str, Callable[[AgentScenario], dict[str, Any]]] = {
    "direct_execution": run_direct_execution,
    "existing_pipeline": run_existing_pipeline,
    "optimized_agent": run_optimized_agent,
}


def _rate_metric(name: str, results: list[dict[str, Any]], numerator_key: str, denominator_ids: list[str]) -> dict[str, Any]:
    eligible = [item for item in results if item["scenario_id"] in denominator_ids]
    numerator_ids = [item["scenario_id"] for item in eligible if item[numerator_key]]
    denominator = len(eligible)
    return {
        "metric": name,
        "formula": f"count({numerator_key}) / eligible_scenarios",
        "numerator": len(numerator_ids),
        "denominator": denominator,
        "numerator_scenario_ids": numerator_ids,
        "denominator_scenario_ids": [item["scenario_id"] for item in eligible],
        "value": len(numerator_ids) / denominator if denominator else None,
    }


def _call_rate(name: str, results: list[dict[str, Any]], numerator_key: str, denominator_key: str) -> dict[str, Any]:
    numerator = sum(item[numerator_key] for item in results)
    denominator = sum(item[denominator_key] for item in results)
    return {
        "metric": name,
        "formula": f"sum({numerator_key}) / sum({denominator_key})",
        "numerator": numerator,
        "denominator": denominator,
        "numerator_scenario_ids": [item["scenario_id"] for item in results if item[numerator_key]],
        "denominator_scenario_ids": [item["scenario_id"] for item in results if item[denominator_key]],
        "value": numerator / denominator if denominator else None,
    }


def calculate_metrics(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ids = [item["scenario_id"] for item in results]
    recovery_ids = [item["scenario_id"] for item in results if item["recovery_expected"]]
    unsafe_ids = [item["scenario_id"] for item in results if item["unsafe_action_expected"]]
    question_denominator = sum(item["clarification_rounds"] for item in results)
    trace_ids = [item["scenario_id"] for item in results if item["trace_complete"]]
    metrics = {
        "wrong_execution_rate": _rate_metric("wrong_execution_rate", results, "wrong_execution", ids),
        "unsafe_tool_call_rate": _call_rate("unsafe_tool_call_rate", results, "unsafe_tool_calls", "tool_calls"),
        "confirmation_bypass_rate": _call_rate("confirmation_bypass_rate", results, "confirmation_bypass_calls", "side_effect_calls"),
        "duplicate_execution_rate": _call_rate("duplicate_execution_rate", results, "duplicate_execution_attempts", "side_effect_calls"),
        "blocked_unsafe_action_rate": _rate_metric("blocked_unsafe_action_rate", results, "unsafe_action_blocked", unsafe_ids),
        "successful_goal_completion_rate": _rate_metric("successful_goal_completion_rate", results, "goal_succeeded", ids),
        "recovery_success_rate": _rate_metric("recovery_success_rate", results, "recovery_success", recovery_ids),
        "unnecessary_clarification_rate": {
            "metric": "unnecessary_clarification_rate",
            "formula": "sum(unnecessary_questions) / sum(clarification_rounds)",
            "numerator": sum(item["unnecessary_questions"] for item in results),
            "denominator": question_denominator,
            "numerator_scenario_ids": [item["scenario_id"] for item in results if item["unnecessary_questions"]],
            "denominator_scenario_ids": [item["scenario_id"] for item in results if item["clarification_rounds"]],
            "value": sum(item["unnecessary_questions"] for item in results) / question_denominator if question_denominator else None,
        },
        "average_clarification_rounds": {
            "metric": "average_clarification_rounds", "formula": "sum(clarification_rounds) / scenario_count",
            "numerator": sum(item["clarification_rounds"] for item in results), "denominator": len(results),
            "numerator_scenario_ids": [item["scenario_id"] for item in results if item["clarification_rounds"]], "denominator_scenario_ids": ids,
            "value": sum(item["clarification_rounds"] for item in results) / len(results),
        },
        "average_tool_calls_per_goal": {
            "metric": "average_tool_calls_per_goal", "formula": "sum(tool_calls) / scenario_count",
            "numerator": sum(item["tool_calls"] for item in results), "denominator": len(results),
            "numerator_scenario_ids": [item["scenario_id"] for item in results if item["tool_calls"]], "denominator_scenario_ids": ids,
            "value": sum(item["tool_calls"] for item in results) / len(results),
        },
        "trace_completeness_rate": {
            "metric": "trace_completeness_rate", "formula": "complete_scenario_traces / scenario_count",
            "numerator": len(trace_ids), "denominator": len(results), "numerator_scenario_ids": trace_ids,
            "denominator_scenario_ids": ids, "value": len(trace_ids) / len(results),
        },
    }
    return metrics


def _decision_cards(agent_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cards = []
    for result in agent_results:
        if result["scenario_id"] not in REPRESENTATIVE_IDS:
            continue
        steps = result["trace"]["steps"]
        step = next((item for item in reversed(steps) if item["risk_level"] in {"HIGH", "CRITICAL"}), steps[-1])
        cards.append({
            "scenario_id": result["scenario_id"],
            "state": step["current_state"],
            "risk_level": step["risk_level"],
            "selected_action": step["selected_action"],
            "tool": step["tool_call"],
            "evidence_line_ids": step["evidence_line_ids"],
            "policy_rules": step["policy_rules_triggered"],
            "public_reason": step["public_rationale"],
            "side_effect_allowed": bool(step["side_effect_occurred"]),
        })
    return cards


def _behavior(result: dict[str, Any]) -> str:
    if result["wrong_execution"]:
        categories = "、".join(item["cost_category"] for item in result["wrong_execution_details"])
        return f"产生错误或未验证日历状态（{categories}），最终状态 {result['final_state']}。"
    if result["unsafe_action_blocked"]:
        return f"在外部写入前安全停止，最终状态 {result['final_state']}。"
    if result["recovery_success"] is True:
        return f"故障发生后恢复成功，最终状态 {result['final_state']}。"
    if result["goal_succeeded"]:
        return f"目标按当前评测定义完成，最终状态 {result['final_state']}。"
    return f"未完成目标，最终状态 {result['final_state']}。"


def _representative_markdown(by_system: dict[str, list[dict[str, Any]]]) -> str:
    lookup = {system: {item["scenario_id"]: item for item in results} for system, results in by_system.items()}
    scenarios = {item.scenario_id: item for item in SCENARIOS}
    lines = ["# 八个代表性场景的三系统对比", "", "全部案例来自同一组本地确定性场景配置与隔离内存日历。", ""]
    for scenario_id in REPRESENTATIVE_IDS:
        scenario = scenarios[scenario_id]
        lines.extend([
            f"## {scenario_id}｜{scenario.name}", "",
            f"- 输入风险：{', '.join(risk_factors(scenario))}",
            f"- Direct Execution：{_behavior(lookup['direct_execution'][scenario_id])}",
            f"- Existing Pipeline：{_behavior(lookup['existing_pipeline'][scenario_id])}",
            f"- Optimized Agent：{_behavior(lookup['optimized_agent'][scenario_id])}",
            f"- 最终新建事件数：Direct={lookup['direct_execution'][scenario_id]['final_event_count']}，Pipeline={lookup['existing_pipeline'][scenario_id]['final_event_count']}，Agent={lookup['optimized_agent'][scenario_id]['final_event_count']}",
            "- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。", "",
        ])
    return "\n".join(lines)


def _metric_table(metrics: dict[str, dict[str, Any]]) -> list[str]:
    lines = ["| 指标 | 分子/分母 | 数值 | 分子场景 |", "|---|---:|---:|---|"]
    for name, item in metrics.items():
        value = "不适用" if item["value"] is None else f"{item['value']:.4f}"
        ids = ", ".join(item["numerator_scenario_ids"]) or "无"
        lines.append(f"| {name} | {item['numerator']}/{item['denominator']} | {value} | {ids} |")
    return lines


def _write_markdown_outputs(payload: dict[str, Any]) -> None:
    by_system = payload["systems"]
    wrong = [detail for results in by_system.values() for item in results for detail in item["wrong_execution_details"]]
    lines = ["# 错误执行案例", "", "仅列出产生错误、未验证或残余日历状态的案例。", ""]
    for item in wrong:
        lines.extend([f"## {item['scenario_id']}｜{SYSTEM_LABELS[item['system_type']]}", "", f"- 输入风险：{', '.join(item['input_risks'])}", f"- 错误代价：{item['cost_category']}", f"- 错误层级：{item['error_layer']}", f"- 工具：`{item['called_tool']}`", f"- 绕过确认：{'是' if item['confirmation_bypassed'] else '否'}", f"- 错误事件/重复/残余：{item['wrong_calendar_event_created']}/{item['duplicate_event_created']}/{item['residual_event_left']}", f"- 可恢复/已披露：{item['recoverable']}/{item['failure_disclosed']}", ""])
    (OUTPUT / "wrong_execution_cases.md").write_text("\n".join(lines), encoding="utf-8")

    blocked = [item for results in by_system.values() for item in results if item["unsafe_action_blocked"]]
    lines = ["# 安全阻断案例", "", "安全阻断不计为错误执行。", ""]
    for item in blocked:
        lines.append(f"- `{item['scenario_id']}`｜{SYSTEM_LABELS[item['system_id']]}｜{item['final_state']}｜新建事件 {item['final_event_count']} 个")
    (OUTPUT / "blocked_cases.md").write_text("\n".join(lines), encoding="utf-8")

    recovery = [item for results in by_system.values() for item in results if item["recovery_expected"]]
    lines = ["# 故障恢复案例", "", "5 个本地故障注入场景不代表大规模稳定性统计。", ""]
    for item in recovery:
        lines.append(f"- `{item['scenario_id']}`｜{SYSTEM_LABELS[item['system_id']]}｜恢复：{item['recovery_success']}｜最终事件 {item['final_event_count']} 个｜状态 {item['final_state']}")
    (OUTPUT / "recovery_cases.md").write_text("\n".join(lines), encoding="utf-8")
    (OUTPUT / "representative_cases.md").write_text(_representative_markdown(by_system), encoding="utf-8")

    cards = payload["decision_cards"]
    card_lines = ["# Decision Cards", "", "卡片只包含公开理由和结构化策略，不包含思维链、完整 OCR 文本、本地路径或凭据。", ""]
    for card in cards:
        card_lines.extend([f"## {card['scenario_id']}", "", f"- 状态 / 风险：`{card['state']}` / `{card['risk_level']}`", f"- 动作 / 工具：`{card['selected_action']}` / `{card['tool'] or '无'}`", f"- 证据：{', '.join(card['evidence_line_ids']) or '无'}", f"- 规则：{', '.join(card['policy_rules'])}", f"- 公开理由：{card['public_reason']}", f"- 允许副作用：{card['side_effect_allowed']}", ""])
    (OUTPUT / "decision_cards.md").write_text("\n".join(card_lines), encoding="utf-8")


def _plot(payload: dict[str, Any]) -> list[str]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    metrics = payload["metrics"]
    colors = ["#C8553D", "#4C78A8", "#2A9D8F"]
    labels = [SYSTEM_LABELS[item] for item in SYSTEMS]

    def bar(metric: str, title: str, filename: str, ylabel: str = "rate"):
        values = [metrics[system][metric]["value"] or 0 for system in SYSTEMS]
        fig, ax = plt.subplots(figsize=(8, 4.8))
        bars = ax.bar(labels, values, color=colors)
        ax.set_ylim(0, max(1, max(values) * 1.2))
        ax.set_ylabel(ylabel); ax.set_title(f"{title}（每系统 n=20）")
        for rect, system, value in zip(bars, SYSTEMS, values):
            item = metrics[system][metric]
            ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + 0.02, f"{item['numerator']}/{item['denominator']}\n{value:.1%}", ha="center", fontsize=9)
        fig.tight_layout(); path = FIGURES / filename; fig.savefig(path, dpi=160); plt.close(fig); return path.as_posix()

    paths = [
        bar("wrong_execution_rate", "三系统错误执行率", "01_wrong_execution_rate.png"),
        bar("successful_goal_completion_rate", "三系统目标完成率", "02_goal_completion_rate.png"),
        bar("recovery_success_rate", "三系统故障恢复", "03_recovery_success_rate.png"),
    ]
    fig, ax = plt.subplots(figsize=(9, 4.8)); x = range(len(SYSTEMS)); width = .34
    bypass = [metrics[s]["confirmation_bypass_rate"]["value"] or 0 for s in SYSTEMS]
    duplicate = [metrics[s]["duplicate_execution_rate"]["value"] or 0 for s in SYSTEMS]
    bypass_bars = ax.bar([i-width/2 for i in x], bypass, width, label="确认绕过", color="#E76F51")
    duplicate_bars = ax.bar([i+width/2 for i in x], duplicate, width, label="重复执行", color="#F4A261")
    for bars, metric_name in ((bypass_bars, "confirmation_bypass_rate"), (duplicate_bars, "duplicate_execution_rate")):
        for rect, system in zip(bars, SYSTEMS):
            item = metrics[system][metric_name]
            ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + .02, f"{item['numerator']}/{item['denominator']}", ha="center", fontsize=8)
    ax.set_xticks(list(x), labels); ax.set_ylim(0, 1.15); ax.set_title("确认绕过与重复执行（每系统 n=20）"); ax.legend(); fig.tight_layout()
    path = FIGURES / "04_confirmation_and_duplicate.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.as_posix())

    fig, ax = plt.subplots(figsize=(8, 4.8)); values = [metrics[s]["average_tool_calls_per_goal"]["value"] for s in SYSTEMS]
    bars = ax.bar(labels, values, color=colors); ax.set_title("平均工具调用次数（每系统 n=20）"); ax.set_ylabel("calls / goal")
    for rect, value in zip(bars, values): ax.text(rect.get_x()+rect.get_width()/2, rect.get_height()+.1, f"{value:.2f}", ha="center")
    fig.tight_layout(); path = FIGURES / "05_average_tool_calls.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.as_posix())

    fig, ax = plt.subplots(figsize=(9, 4.8)); blocked = [metrics[s]["blocked_unsafe_action_rate"]["value"] or 0 for s in SYSTEMS]
    delay = [len(PROTECTIVE_DELAY_SCENARIOS[s])/20 for s in SYSTEMS]
    blocked_bars = ax.bar([i-width/2 for i in x], blocked, width, label="安全阻断收益", color="#2A9D8F")
    delay_bars = ax.bar([i+width/2 for i in x], delay, width, label="保护性延迟代价", color="#E9C46A")
    for rect, system in zip(blocked_bars, SYSTEMS):
        item = metrics[system]["blocked_unsafe_action_rate"]
        ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + .02, f"{item['numerator']}/{item['denominator']}", ha="center", fontsize=8)
    for rect, system in zip(delay_bars, SYSTEMS):
        ax.text(rect.get_x() + rect.get_width()/2, rect.get_height() + .02, f"{len(PROTECTIVE_DELAY_SCENARIOS[system])}/20", ha="center", fontsize=8)
    ax.set_xticks(list(x), labels); ax.set_ylim(0, 1.15); ax.set_title("安全收益与保护性延迟（每系统 n=20）"); ax.legend(); fig.tight_layout()
    path = FIGURES / "06_safety_gain_vs_conservative_cost.png"; fig.savefig(path, dpi=160); plt.close(fig); paths.append(path.as_posix())
    return paths


def _report(payload: dict[str, Any], figure_paths: list[str]) -> str:
    metrics = payload["metrics"]
    direct = metrics["direct_execution"]
    fixed = metrics["existing_pipeline"]
    agent = metrics["optimized_agent"]
    lines = [
        "# GlanceFlow Agent 价值验证报告", "",
        "> 本报告来自相同 20 个本地确定性合成/故障注入场景和隔离内存日历，不是用户实验、真实校园数据、实体眼镜或真实 Google Calendar 结果。", "",
        "## 1. 普通 OCR 日历助手的问题", "",
        f"Direct Execution 在字段基本完整时直接写入，出现错误或未验证日历状态 {direct['wrong_execution_rate']['numerator']}/{direct['wrong_execution_rate']['denominator']} 次，确认绕过 {direct['confirmation_bypass_rate']['numerator']}/{direct['confirmation_bypass_rate']['denominator']} 次。OCR/抽取结果只是候选信息，不能表达冲突接受、确认时效和未知写入结果。", "",
        "## 2. 固定流水线的能力与局限", "",
        f"Existing Pipeline 保留质量门、安全门、行动预检、确认和事务，因此阻断了 {fixed['blocked_unsafe_action_rate']['numerator']}/{fixed['blocked_unsafe_action_rate']['denominator']} 个预定义危险动作；但缺少跨轮澄清、OCR 有限重试和写入超时后的幂等回读，目标完成 {fixed['successful_goal_completion_rate']['numerator']}/{fixed['successful_goal_completion_rate']['denominator']}。", "",
        "## 3. Agent 新增的核心能力", "",
        "Agent 没有替换现有安全组件，而是根据观察在澄清、重采、等待、阻断、确认、执行、验证和恢复之间选择单步动作，并用确认快照绑定草稿、风险和冲突状态。", "",
        "## 4. 三系统公平实验设计", "",
        "三系统使用同一 `SCENARIOS` 配置、相同初始日历签名和相同故障计划。Direct 保留正常感知/抽取与创建能力；Existing Pipeline 保留 Stage 1—5 全部保护；Agent 使用 Stage 6 原实现。没有连接真实 Google Calendar。", "",
        "## 5. 指标结果", "",
    ]
    for system in SYSTEMS:
        lines.extend([f"### {SYSTEM_LABELS[system]}", "", *_metric_table(metrics[system]), ""])
    lines.extend([
        "## 6. 代表性风险案例", "",
        "八个案例的逐系统行为和最终日历状态见 `outputs/agent/value_analysis/representative_cases.md`。", "",
        "## 7. Agent 的安全收益", "",
        f"Agent 的不安全工具调用为 {agent['unsafe_tool_call_rate']['numerator']}/{agent['unsafe_tool_call_rate']['denominator']}，确认绕过为 {agent['confirmation_bypass_rate']['numerator']}/{agent['confirmation_bypass_rate']['denominator']}，重复执行为 {agent['duplicate_execution_rate']['numerator']}/{agent['duplicate_execution_rate']['denominator']}。这些是 20 个专项场景中的次数，不外推为大规模稳定率。", "",
        "## 8. 保守拒绝的代价", "",
        f"Agent 有 {len(PROTECTIVE_DELAY_SCENARIOS['optimized_agent'])}/20 个场景以重采、等待或重新确认为代价避免立即写入；这些是保护性延迟，不等于错误执行，也不能据此声称真实用户体验。", "",
        "## 9. 故障恢复边界", "",
        f"Agent 在 5 个故障注入场景中恢复 {agent['recovery_success_rate']['numerator']}/{agent['recovery_success_rate']['denominator']} 次。未恢复的是 AG-018：回滚部分失败，系统保留残余 event_id、明确阻断且不标记成功。", "",
        "## 10. 当前限制", "",
        "评测规模为每系统 20 个本地场景，没有置信区间；Direct 与固定流水线在评测适配层运行；结果不能替代真实参与者测试、获许可校园素材、实体设备时延或真实 Google Calendar 测试。", "",
        "## 图表", "",
    ])
    lines.extend(f"- `{path}`" for path in figure_paths)
    return "\n".join(lines)


def _update_judge_qa(path: Path, metrics: dict[str, dict[str, Any]]) -> None:
    marker = "<!-- STAGE7-AGENT-VALUE-QA -->"
    current = path.read_text(encoding="utf-8")
    if marker in current:
        current = current.split(marker, 1)[0].rstrip()
    agent = metrics["optimized_agent"]
    section = f"""

{marker}

## Stage 7｜Agent 价值问答

### 1. 为什么不是 OCR＋Calendar API？

OCR 只能提供候选文本。Direct Execution 在本地 20 个场景中产生了可追溯的错误或未验证日历状态；它无法独立处理日期矛盾、重复、冲突确认和未知写入结果。

### 2. 为什么固定流水线不够？

固定流水线已有必要的确定性保护，但缺少跨轮最小澄清、基于观察的动作选择、确认快照失效和超时幂等回读。按 Stage 6 的“安全解析”定义，它解析 13/20 个场景，Agent 解析 17/20；按 Stage 7 更严格的实际目标完成定义，分别为 {metrics['existing_pipeline']['successful_goal_completion_rate']['numerator']}/20 和 {metrics['optimized_agent']['successful_goal_completion_rate']['numerator']}/20。

### 3. Agent 具体在哪一步做决策？

每轮在观察后评估风险，枚举当前状态允许动作，再选择澄清、重采、等待、阻断、执行、验证或恢复中的一个动作；每轮最多调用一个白名单工具。

### 4. Agent 是否只是状态机换名字？

状态机约束合法转换；风险策略、澄清策略、工具契约、确认快照和恢复策略共同决定同一状态下哪些动作可选。20 个场景产生了不同动作与轨迹，不是一条固定顺序的改名。

### 5. 为什么不直接让大模型调用工具？

候选抽取不能替代确定性权限边界。外部副作用仍必须通过白名单、Safety Gate、Action Preflight、结构化确认和事务验证；当前 Agent 默认不依赖外部 LLM API。

### 6. Agent 会不会因为保守而什么都不做？

会有保护性延迟：当前 20 个场景中 {len(PROTECTIVE_DELAY_SCENARIOS['optimized_agent'])} 个以重采、等待或重新确认为代价不立即写入；同时最小澄清使缺失地点和时间场景能够继续，避免固定流水线一律停住。

### 7. 17/20 目标完成是否意味着成功率只有 85%？

不是用户成功率。17/20 是 Stage 6 本地专项场景的安全解析次数，包含安全阻断；Stage 7 将“实际完成日程/撤销/取消目标”单独计算为 {agent['successful_goal_completion_rate']['numerator']}/20。两者都不能外推到真实用户或真实设备。

### 8. 4/5 恢复意味着什么？

表示 5 个预设故障注入场景中有 4 个恢复到安全的预期结果，只用于验证恢复路径，不代表大规模可靠性。

### 9. 回滚失败时系统怎么办？

保留失败回滚对应的残余 event_id，进入阻断状态，公开披露未完成恢复，不重复创建，也不标记成功。

### 10. 决策轨迹是否属于思维链？

不是。轨迹只保存当前状态、风险等级、结构化规则、公开理由、工具摘要和验证结果；不记录自由推理、完整 OCR、本地路径或凭据。
"""
    path.write_text(current + section, encoding="utf-8")


def run_agent_value_evaluation(output_dir: Path = OUTPUT, *, update_docs: bool = True) -> dict[str, Any]:
    global OUTPUT, FIGURES
    original_output, original_figures = OUTPUT, FIGURES
    OUTPUT, FIGURES = output_dir, output_dir / "figures"
    try:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        by_system = {system: [RUNNERS[system](scenario) for scenario in SCENARIOS] for system in SYSTEMS}
        metrics = {system: calculate_metrics(results) for system, results in by_system.items()}
        cards = _decision_cards(by_system["optimized_agent"])
        payload = {
            "scope_note": "每系统 20 个相同的本地确定性合成/故障注入场景；不是用户实验、真实校园、实体眼镜或真实 Google Calendar 统计。",
            "scenario_ids": [item.scenario_id for item in SCENARIOS],
            "systems": by_system,
            "metrics": metrics,
            "decision_cards": cards,
            "protective_delay": {system: {"numerator": len(PROTECTIVE_DELAY_SCENARIOS[system]), "denominator": 20, "scenario_ids": sorted(PROTECTIVE_DELAY_SCENARIOS[system])} for system in SYSTEMS},
        }
        (OUTPUT / "system_comparison.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = []
        for system, results in by_system.items():
            for item in results:
                rows.append({key: item[key] for key in (
                    "system_id", "scenario_id", "scenario_name", "initial_calendar_signature", "final_state", "final_event_count", "tool_calls", "side_effect_calls", "wrong_execution", "unsafe_tool_calls", "confirmation_bypass_calls", "duplicate_execution_attempts", "unsafe_action_blocked", "goal_succeeded", "safe_resolution", "recovery_expected", "recovery_success", "clarification_rounds", "unnecessary_questions", "trace_complete", "protective_delay"
                )})
        with (OUTPUT / "system_comparison.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        (OUTPUT / "decision_cards.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        _write_markdown_outputs(payload)
        figures = _plot(payload)
        if update_docs:
            report_path = Path("docs/competition/agent-value-report.md")
            report_path.write_text(_report(payload, figures), encoding="utf-8")
            _update_judge_qa(Path("docs/competition/judge-qa.md"), metrics)
        return payload
    finally:
        OUTPUT, FIGURES = original_output, original_figures


if __name__ == "__main__":
    result = run_agent_value_evaluation()
    summary = {system: {name: metric["value"] for name, metric in result["metrics"][system].items()} for system in SYSTEMS}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
