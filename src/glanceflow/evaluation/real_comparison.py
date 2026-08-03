from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.evaluation.real_data import OUTCOMES, fraction


DEFAULT_SYNTHETIC = Path("outputs/evaluation/full_system_results.json")
DEFAULT_REAL = Path("outputs/evaluation/real_data/real_data_results.json")
DEFAULT_OUTPUT = Path("outputs/evaluation/real_data")
COMPARISON_METRICS = (
    "full_field_correct_rate", "BUSINESS_COMPLETED", "SAFE_DEFERRED", "SAFE_BLOCKED",
    "WRONG_EXECUTION", "recapture_rate", "ocr_failure_rate",
    "average_confirmation_count", "average_latency_ms",
)


def _synthetic_outcome(row: dict[str, Any]) -> str:
    if row["erroneous_execution"]:
        return "WRONG_EXECUTION"
    if row["correct_execution"]:
        return "BUSINESS_COMPLETED"
    if row.get("rollback_attempted") and row.get("rollback_succeeded") is False:
        return "RECOVERY_PENDING"
    if row["predicted_safety_status"] in {SafetyGateStatus.NEED_USER_INPUT.value, SafetyGateStatus.RECAPTURE_REQUIRED.value}:
        return "SAFE_DEFERRED"
    if row["predicted_safety_status"] == SafetyGateStatus.CONTRADICTION_BLOCKED.value:
        return "SAFE_BLOCKED"
    return "SYSTEM_FAILED"


def summarize_synthetic(path: Path = DEFAULT_SYNTHETIC) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["results"]
    total = len(rows)
    outcomes = [_synthetic_outcome(row) for row in rows]
    counts = {name: outcomes.count(name) for name in OUTCOMES}
    return {
        "status": "EXECUTED", "sample_count": total, "outcome_counts": counts,
        "metrics": {
            "full_field_correct_rate": fraction(sum(bool(row["fields_match"]) for row in rows), total),
            "BUSINESS_COMPLETED": fraction(counts["BUSINESS_COMPLETED"], total),
            "SAFE_DEFERRED": fraction(counts["SAFE_DEFERRED"], total),
            "SAFE_BLOCKED": fraction(counts["SAFE_BLOCKED"], total),
            "WRONG_EXECUTION": fraction(counts["WRONG_EXECUTION"], total),
            "recapture_rate": fraction(sum(row["predicted_safety_status"] == SafetyGateStatus.RECAPTURE_REQUIRED.value for row in rows), total),
            "ocr_failure_rate": fraction(sum(not bool(row.get("ocr_lines")) for row in rows), total),
            "average_confirmation_count": sum(row.get("transaction_status") is not None for row in rows) / total,
            "average_latency_ms": sum(row["latencies"]["total_ms"] for row in rows) / total,
        },
    }


def _real_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload["summary"]
    if summary["status"] != "EXECUTED":
        return {"status": "NOT_EXECUTED", "sample_count": 0, "outcome_counts": {name: None for name in OUTCOMES}, "metrics": {}}
    total = summary["sample_count"]
    counts = summary["outcome_counts"]
    metrics = summary["metrics"]
    return {
        "status": "EXECUTED", "sample_count": total, "outcome_counts": counts,
        "metrics": {
            "full_field_correct_rate": metrics["full_field_correct_rate"],
            "BUSINESS_COMPLETED": fraction(counts["BUSINESS_COMPLETED"], total),
            "SAFE_DEFERRED": fraction(counts["SAFE_DEFERRED"], total),
            "SAFE_BLOCKED": fraction(counts["SAFE_BLOCKED"], total),
            "WRONG_EXECUTION": fraction(counts["WRONG_EXECUTION"], total),
            "recapture_rate": metrics["recapture_rate"],
            "ocr_failure_rate": fraction(sum(not row["ocr_success"] for row in payload["results"]), total),
            "average_confirmation_count": metrics["average_confirmation_count"],
            "average_latency_ms": metrics["average_latency_ms"],
        },
    }


def _display(value: Any) -> str:
    if value is None:
        return "NOT EXECUTED"
    if isinstance(value, dict):
        return value.get("display", "NOT EXECUTED")
    return f"{value:.3f}"


def _report(payload: dict[str, Any]) -> str:
    synthetic, real = payload["synthetic"], payload["real"]
    lines = [
        "# 合成数据与真实校园小样本对比", "",
        f"合成集 N={synthetic['sample_count']}；真实集：{real['sample_count'] if real['status'] == 'EXECUTED' else 'NOT EXECUTED'}。", "",
    ]
    if real["status"] != "EXECUTED":
        lines.extend([
            "**NOT EXECUTED**", "",
            "尚未采集真实校园素材，因此不计算差值、不推断真实困难，也不宣称统计显著性。",
        ])
        return "\n".join(lines)
    lines.extend(["> 仅为小规模真实场景验证，不进行统计显著性声明。", "", "| 指标 | 合成数据 | 真实数据 |", "|---|---:|---:|"])
    for name in COMPARISON_METRICS:
        lines.append(f"| {name} | {_display(synthetic['metrics'][name])} | {_display(real['metrics'][name])} |")
    lines.extend(["", "## 新增困难", "", "仅记录真实失败案例中有证据支持的困难；详见 Stage 8 failure analysis，不根据空白模板推测。"])
    return "\n".join(lines)


def compare_real_vs_synthetic(
    synthetic_path: Path = DEFAULT_SYNTHETIC,
    real_path: Path = DEFAULT_REAL,
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    synthetic = summarize_synthetic(synthetic_path)
    real_payload = json.loads(real_path.read_text(encoding="utf-8"))
    real = _real_metrics(real_payload)
    payload = {
        "scope": "46 synthetic samples vs small permitted real-campus sample",
        "statistical_significance_claimed": False,
        "synthetic": synthetic,
        "real": real,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "real_vs_synthetic.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "real_vs_synthetic.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("metric", "synthetic", "real"))
        writer.writeheader()
        for name in COMPARISON_METRICS:
            writer.writerow({"metric": name, "synthetic": _display(synthetic["metrics"][name]), "real": _display(real["metrics"].get(name))})
    (output_dir / "real_vs_synthetic.md").write_text(_report(payload), encoding="utf-8")
    return payload


def main() -> int:
    result = compare_real_vs_synthetic()
    print(json.dumps({"synthetic_n": result["synthetic"]["sample_count"], "real_status": result["real"]["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
