from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from glanceflow.evaluation.real_comparison import compare_real_vs_synthetic
from glanceflow.evaluation.real_data import OUTCOMES, evaluate_real_data
from glanceflow.evaluation.public_web import evaluate_public_web, compare_public_web_vs_synthetic
from glanceflow.evaluation.user_study import load_records, run_user_study_analysis


HANDOFF = Path("docs/handoff/stage8-real-data-user-validation.md")
FAILURES = Path("docs/handoff/stage8-failure-analysis.md")
STATUS = Path("outputs/evaluation/stage8_status.json")


def _stage7_baseline(path: Path = Path("outputs/agent/value_analysis/system_comparison.json")) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    counts = payload["outcome_counts"]["optimized_agent"]
    metrics = payload["metrics"]["optimized_agent"]
    return {
        "wrong_execution": counts["WRONG_EXECUTION"]["count"],
        "business_completed": counts["BUSINESS_COMPLETED"]["count"],
        "unsafe_tool_calls": metrics["unsafe_tool_call_rate"]["numerator"],
        "confirmation_bypass": metrics["confirmation_bypass_rate"]["numerator"],
        "duplicate_execution": metrics["duplicate_execution_rate"]["numerator"],
        "recovery": f"{metrics['recovery_success_rate']['numerator']}/{metrics['recovery_success_rate']['denominator']}",
    }


def _failure_rows(real_payload: dict[str, Any], user_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in real_payload["results"]:
        if item["agent_final_classification"] == "BUSINESS_COMPLETED":
            continue
        rows.append({
            "trace_id": item["sample_id"], "scenario": "real campus notice",
            "expected": item["expected_behavior"], "actual": item["agent_final_classification"],
            "root_cause": item["final_reason"],
            "safety_impact": "Review before changing Agent behavior.",
            "user_impact": "May require recapture, clarification, blocking, or recovery.",
            "recommended_next_step": "Preserve the sample; triage as evaluation evidence for Stage 9 or later.",
        })
    for item in user_rows:
        if item["completed"] and not item["incorrect_action"] and not item["recovery_required"]:
            continue
        rows.append({
            "trace_id": f"{item['participant_id']}/{item['task_id']}", "scenario": "real participant task",
            "expected": "task completed without incorrect action or unresolved recovery",
            "actual": item["agent_final_classification"] or item["calendar_result"] or "task incomplete",
            "root_cause": item["observer_note"] or "Requires observer review.",
            "safety_impact": "Inspect any incorrect action or unresolved recovery before Agent changes.",
            "user_impact": "Task failed, required recovery, or produced an incorrect action.",
            "recommended_next_step": "Preserve the anonymous task row and triage for Stage 9 or later.",
        })
    return rows


def _failure_report(real_payload: dict[str, Any], user_summary: dict[str, Any], user_rows: list[dict[str, Any]]) -> str:
    rows = _failure_rows(real_payload, user_rows)
    if real_payload["summary"]["status"] != "EXECUTED" and not user_summary["results_available"]:
        return """# Stage 8 Failure Analysis

**NOT EXECUTED**

真实校园评测和真人用户实验均未执行，因此没有真实失败案例、Decision Trace 或真实世界失败模式可分析。不得从合成数据推测真实失败。

| sample_id / participant_id | scenario | expected | actual | root_cause | safety_impact | user_impact | recommended_next_step |
|---|---|---|---|---|---|---|---|
"""
    lines = [
        "# Stage 8 Failure Analysis", "",
        "本报告仅保留真实执行中观察到的失败，不删除失败样本，也不把安全阻断改写为成功。", "",
        "| sample_id / participant_id | scenario | expected | actual | root_cause | safety_impact | user_impact | recommended_next_step |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {row['trace_id']} | {row['scenario']} | {row['expected']} | {row['actual']} | {row['root_cause']} | {row['safety_impact']} | {row['user_impact']} | {row['recommended_next_step']} |"
        for row in rows
    )
    if not rows:
        lines.append("| NOT OBSERVED | — | — | — | — | — | — | — |")
    lines.extend(["", "## Decision Trace", "", "真实样本不足时不生成 Observe → Risk → Decision → Tool → Result → Verify 案例。"])
    return "\n".join(lines)


def _value(value: Any) -> str:
    return "NOT EXECUTED" if value is None else str(value)


def _handoff_report(
    real_payload: dict[str, Any], user_summary: dict[str, Any], comparison: dict[str, Any],
    baseline: dict[str, Any], full_test_result: str,
) -> str:
    real = real_payload["summary"]
    real_results_available = real["status"] == "EXECUTED"
    user_results_available = bool(user_summary["results_available"])
    real_executed = real_results_available and real["target_met"]
    user_executed = user_results_available and user_summary["protocol_complete"]
    counts = real["outcome_counts"]
    real_status = "Real-data validation executed" if real_executed else "NOT EXECUTED"
    user_status = "User study executed" if user_executed else "NOT EXECUTED"
    return f"""# Stage 8 Real Data & User Validation

> 工程状态：**Stage 8 infrastructure complete**。该状态不等于真实数据或真人用户实验已经执行。

## 1. Git 起始状态

从包含 PR #3 的 `main` 合并提交 `9caa803` 创建 `stage8/real-data-user-validation`；未直接修改或推送 `main`。

## 2. Stage 7 基线测试

进入 Stage 8 前全量测试：`196 passed`。Agent Value 回归：WRONG_EXECUTION {baseline['wrong_execution']}/20，BUSINESS_COMPLETED {baseline['business_completed']}/20，unsafe tool calls {baseline['unsafe_tool_calls']}，confirmation bypass {baseline['confirmation_bypass']}，duplicate execution {baseline['duplicate_execution']}，recovery {baseline['recovery']}。

## 3. Stage 8 新增实现

真实数据 schema 与三重门禁、标注追溯、隐私扫描、现有 OCR/抽取/Safety Gate/事务评测适配、六分类汇总、合成/真实对比、真人日志校验与统计、机器生成报告及测试。

## 4. 真实校园素材数量

{real['sample_count'] if real_results_available else 'NOT EXECUTED（当前已提交 0 张）'}。

## 5. 真实素材许可与隐私情况

{'全部通过 manifest 门禁' if real_results_available else 'NOT EXECUTED；无真实素材可核验。'}

## 6. 真实数据最终评测

{real_status if real_executed or not real_results_available else 'PARTIAL COLLECTION；已有结果但未达到 10—20 张完成条件'}。

## 7. 合成 vs 真实差异

{'见 outputs/evaluation/real_data/real_vs_synthetic.md' if real_results_available else 'NOT EXECUTED；不根据空数据推测差异。'}

## 8. 真人参与人数

{user_summary['participants'] if user_results_available else 'NOT EXECUTED（当前 0 人）'}。

## 9. 真人任务总数

{user_summary.get('total_tasks') if user_results_available else 'NOT EXECUTED'}。

## 10. 用户实验结果

{user_status if user_executed or not user_results_available else 'PARTIAL COLLECTION；未达到 5—8 人且每人完成 T1—T6 的条件'}。

## 11. 失败案例

{'见 stage8-failure-analysis.md' if real_results_available or user_results_available else 'NOT EXECUTED'}。

## 12. 是否出现 WRONG_EXECUTION

{_value(counts['WRONG_EXECUTION'])}。

## 13. SAFE_DEFERRED 数量

{_value(counts['SAFE_DEFERRED'])}。

## 14. SAFE_BLOCKED 数量

{_value(counts['SAFE_BLOCKED'])}。

## 15. 是否存在过度保守迹象

{'需结合 SAFE_DEFERRED、SAFE_BLOCKED 与可完成样本逐例审计' if real_results_available else 'NOT EXECUTED；无真实证据。'}

## 16. 新发现限制

当前最主要限制是缺少 10—20 张获许可、完成脱敏和双人复核的校园素材，以及 5—8 名签署同意的真人参与者记录。

## 17. 是否修改 Agent 核心

否。只新增 evaluation 适配、验证、分析与报告层。

## 18. 全量测试结果

`{full_test_result}`。

## 19. 当前仍缺少的数据

真实校园素材、对应许可/隐私复核、逐样本标注，以及真人六任务记录。

## 20. Stage 9 建议

尚不建议以真实验证结论进入 Stage 9。先采集并接入真实素材和真人记录，重新运行本入口并审计失败；实体眼镜适配仍应单独立项。
"""


def run_stage8(*, full_test_result: str = "PENDING FINAL RUN") -> dict[str, Any]:
    real_payload = evaluate_real_data()
    public_web_payload = evaluate_public_web()
    compare_public_web_vs_synthetic()
    user_summary = run_user_study_analysis()
    user_rows = load_records()
    comparison = compare_real_vs_synthetic()
    baseline = _stage7_baseline()
    status = {
        "infrastructure_status": "Stage 8 infrastructure complete",
        "real_data_status": (
            "Real-data validation executed" if real_payload["summary"]["target_met"]
            else "PARTIAL COLLECTION" if real_payload["summary"]["status"] == "EXECUTED"
            else "NOT EXECUTED"
        ),
        "user_study_status": (
            "User study executed" if user_summary["protocol_complete"]
            else "PARTIAL COLLECTION" if user_summary["results_available"]
            else "NOT EXECUTED"
        ),
        "real_sample_count": real_payload["summary"]["sample_count"],
        "public_web_status": public_web_payload["summary"]["status"],
        "public_web_candidates_audited": public_web_payload["candidate_count"],
        "public_web_metadata_selected": public_web_payload["summary"]["selected_sample_count"],
        "public_web_samples_evaluated": public_web_payload["summary"]["sample_count"],
        "participant_count": user_summary["participants"],
        "agent_core_modified": False,
        "full_test_result": full_test_result,
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    HANDOFF.parent.mkdir(parents=True, exist_ok=True)
    HANDOFF.write_text(_handoff_report(real_payload, user_summary, comparison, baseline, full_test_result), encoding="utf-8")
    FAILURES.write_text(_failure_report(real_payload, user_summary, user_rows), encoding="utf-8")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Stage 8 validation and generate reports")
    parser.add_argument("--test-result", default="PENDING FINAL RUN")
    args = parser.parse_args()
    print(json.dumps(run_stage8(full_test_result=args.test_result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
