from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from glanceflow.evaluation.privacy import redact_sensitive_text
from glanceflow.evaluation.real_data import fraction


DEFAULT_RECORDS = Path("evaluation/user_study/record_template.csv")
DEFAULT_OUTPUT = Path("outputs/evaluation/user_study")
TASKS = ("T1", "T2", "T3", "T4", "T5", "T6")
REQUIRED_FIELDS = (
    "participant_id", "session_date", "task_id", "completed", "completion_time_seconds",
    "confirmation_count", "clarification_count", "recapture_count", "incorrect_action",
    "hud_understood", "trust_rating", "burden_rating", "continue_use_rating", "free_comment",
    "agent_final_classification", "calendar_result", "recovery_required", "observer_note",
)


def _bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{field} must be true or false")
    return normalized == "true"


def _int(value: str, field: str, *, low: int = 0, high: int | None = None) -> int:
    number = int(value)
    if number < low or (high is not None and number > high):
        raise ValueError(f"{field} is outside the allowed range")
    return number


def load_records(path: Path = DEFAULT_RECORDS) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REQUIRED_FIELDS:
            raise ValueError("用户实验记录模板字段不完整。")
        raw_rows = [row for row in reader if any((value or "").strip() for value in row.values())]
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        participant = raw["participant_id"].strip()
        if not participant.startswith("P") or len(participant) != 3 or not participant[1:].isdigit():
            raise ValueError("participant_id must use anonymous IDs such as P01")
        if raw["task_id"] not in TASKS:
            raise ValueError("task_id must be one of T1-T6")
        if not raw["session_date"].strip():
            raise ValueError("session_date is required")
        row: dict[str, Any] = dict(raw)
        row["completed"] = _bool(raw["completed"], "completed")
        row["incorrect_action"] = _bool(raw["incorrect_action"], "incorrect_action")
        row["recovery_required"] = _bool(raw["recovery_required"], "recovery_required")
        row["completion_time_seconds"] = float(raw["completion_time_seconds"])
        if row["completion_time_seconds"] < 0:
            raise ValueError("completion_time_seconds must be non-negative")
        for field in ("confirmation_count", "clarification_count", "recapture_count"):
            row[field] = _int(raw[field], field)
        for field in ("hud_understood", "trust_rating", "burden_rating", "continue_use_rating"):
            row[field] = _int(raw[field], field, low=1, high=5)
        row["free_comment"] = redact_sensitive_text(raw["free_comment"]) or ""
        row["observer_note"] = redact_sensitive_text(raw["observer_note"]) or ""
        rows.append(row)
    pairs = [(row["participant_id"], row["task_id"]) for row in rows]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each participant/task pair may appear only once")
    return rows


def _empty_summary() -> dict[str, Any]:
    return {
        "status": "尚未执行", "execution_status": "NOT_EXECUTED", "participants": 0,
        "sessions": 0, "results_available": False, "target_met": False, "protocol_complete": False,
        "message": "尚未执行真人用户实验。",
        "summary": "没有真实记录，不计算 0%、0 秒或 0 分作为实验结果。",
    }


def analyze(path: Path = DEFAULT_RECORDS) -> dict[str, Any]:
    rows = load_records(path)
    if not rows:
        return _empty_summary()
    participants = sorted({row["participant_id"] for row in rows})
    tasks_by_participant = {
        participant: {row["task_id"] for row in rows if row["participant_id"] == participant}
        for participant in participants
    }
    protocol_complete = 5 <= len(participants) <= 8 and all(tasks == set(TASKS) for tasks in tasks_by_participant.values())
    completed = sum(bool(row["completed"]) for row in rows)
    task_counts = Counter(row["task_id"] for row in rows)
    task_completed = Counter(row["task_id"] for row in rows if row["completed"])
    return {
        "status": "已执行", "execution_status": "EXECUTED", "participants": len(participants),
        "target_met": protocol_complete, "protocol_complete": protocol_complete,
        "participant_ids": participants, "sessions": len({(row['participant_id'], row['session_date']) for row in rows}),
        "results_available": True, "total_tasks": len(rows), "completed_tasks": completed,
        "completion_rate": fraction(completed, len(rows)),
        "task_completion": {task: fraction(task_completed[task], task_counts[task]) for task in TASKS if task_counts[task]},
        "time_seconds": {
            "mean": statistics.fmean(row["completion_time_seconds"] for row in rows),
            "median": statistics.median(row["completion_time_seconds"] for row in rows),
        },
        "average_confirmation_count": statistics.fmean(row["confirmation_count"] for row in rows),
        "average_clarification_count": statistics.fmean(row["clarification_count"] for row in rows),
        "average_recapture_count": statistics.fmean(row["recapture_count"] for row in rows),
        "incorrect_action_count": sum(bool(row["incorrect_action"]) for row in rows),
        "ratings": {
            field: {"mean": statistics.fmean(row[field] for row in rows), "n": len(rows)}
            for field in ("hud_understood", "trust_rating", "burden_rating", "continue_use_rating")
        },
    }


def _report(summary: dict[str, Any]) -> str:
    lines = ["# Stage 8 真人用户实验报告", "", "> 本报告由结构化记录自动生成；自定义量表不是 SUS 或 NASA-TLX。"]
    if not summary["results_available"]:
        return "\n".join(lines + ["", "## 状态", "", "**NOT EXECUTED**", "", summary["message"]])
    lines.extend([
        "", "## 样本", "", f"真实匿名参与者 N={summary['participants']}；任务记录 N={summary['total_tasks']}。",
        "", "## 完成情况", "", f"总体完成：{summary['completion_rate']['display']}", "",
        "| 任务 | 完成 |", "|---|---:|",
    ])
    lines.extend(f"| {task} | {value['display']} |" for task, value in summary["task_completion"].items())
    lines.extend([
        "", "## 时间与交互", "",
        f"- 平均/中位任务时间：{summary['time_seconds']['mean']:.2f} / {summary['time_seconds']['median']:.2f} 秒",
        f"- 平均确认/澄清/重拍：{summary['average_confirmation_count']:.2f} / {summary['average_clarification_count']:.2f} / {summary['average_recapture_count']:.2f}",
        f"- 误操作：{summary['incorrect_action_count']}/{summary['total_tasks']}",
        "", "## 自定义 1—5 分量表", "", "| 量表 | 均值 | N |", "|---|---:|---:|",
    ])
    lines.extend(f"| {name} | {value['mean']:.2f} | {value['n']} |" for name, value in summary["ratings"].items())
    return "\n".join(lines)


def run_user_study_analysis(path: Path = DEFAULT_RECORDS, output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    rows = load_records(path)
    summary = analyze(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "user_study_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "user_study_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "user_study_report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def main() -> int:
    print(json.dumps(run_user_study_analysis(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
