from __future__ import annotations

import csv
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from glanceflow.evaluation.audit import build_metric_audit, metric_audit_csv_rows, metric_audit_markdown
from glanceflow.evaluation.charts import generate_figures
from glanceflow.evaluation.dataset import load_manifest
from glanceflow.evaluation.metrics import compute_system_metrics, group_results, latency_statistics
from glanceflow.evaluation.reliability import run_reliability_trials
from glanceflow.evaluation.reports import evaluation_report_markdown, final_scorecard_markdown, select_failure_cases
from glanceflow.evaluation.runners import ABLATIONS, prepare_observations, run_ablation, run_baseline_a, run_baseline_b, run_full_system


OUTPUT = Path("outputs/evaluation")


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None) -> None:
    names = fieldnames or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        writer.writerows(rows)


def run_all() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    annotations = {sample.sample_id: sample for sample in manifest.samples}
    observations = prepare_observations(manifest.samples)
    observed_ids = {item.annotation.sample_id for item in observations}
    if observed_ids != set(annotations):
        raise RuntimeError("三个系统没有获得完全相同的评测样本集合。")

    baseline_a = [run_baseline_a(item) for item in observations]
    baseline_b = [run_baseline_b(item) for item in observations]
    full = [run_full_system(item) for item in observations]
    ablation_results = [run_ablation(item, config) for config in ABLATIONS for item in observations]
    all_core = [*baseline_a, *baseline_b, *full]
    grouped_core = group_results(all_core)
    grouped_ablation = group_results(ablation_results)
    system_metrics = [compute_system_metrics(grouped_core[key], annotations) for key in ("baseline_a_regex_direct", "baseline_b_extractor_no_safety", "full_system")]
    ablation_metrics = [compute_system_metrics(grouped_ablation[config.ablation_id], annotations) for config in ABLATIONS]
    system_metric_data = [item.model_dump(mode="json") for item in system_metrics]
    ablation_metric_data = [item.model_dump(mode="json") for item in ablation_metrics]
    latency_rows = [
        row
        for key in ("baseline_a_regex_direct", "baseline_b_extractor_no_safety", "full_system")
        for row in latency_statistics(grouped_core[key], annotations)
    ]
    reliability = run_reliability_trials(full, observations)
    failures = select_failure_cases(all_core, annotations)

    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": manifest.dataset_id,
        "sample_count": manifest.sample_count,
        "sample_ids": sorted(annotations),
        "environment": f"{platform.system()} {platform.release()}, Python {sys.version.split()[0]}, local CPU simulator",
        "real_glasses": False,
        "real_google_calendar_calls": False,
    }
    _write_json(OUTPUT / "full_system_results.json", {"metadata": metadata, "results": [item.model_dump(mode="json") for item in full], "reliability": reliability})
    _write_json(OUTPUT / "baseline_results.json", {"metadata": metadata, "systems": {"baseline_a_regex_direct": [item.model_dump(mode="json") for item in baseline_a], "baseline_b_extractor_no_safety": [item.model_dump(mode="json") for item in baseline_b]}})
    _write_json(OUTPUT / "ablation_results.json", {"metadata": metadata, "configs": [config.__dict__ | {"disabled_safety_rules": sorted(config.disabled_safety_rules)} for config in ABLATIONS], "results": [item.model_dump(mode="json") for item in ablation_results]})

    metric_rows = []
    for item in [*system_metric_data, *ablation_metric_data]:
        metric_rows.append({
            "system_id": item["system_id"], "sample_count": item["sample_count"],
            "erroneous_execution_rate": item["erroneous_execution_rate"]["value"],
            "erroneous_execution_numerator": item["erroneous_execution_rate"]["numerator"],
            "erroneous_execution_denominator": item["erroneous_execution_rate"]["denominator"],
            "valid_coverage_rate": item["valid_coverage_rate"]["value"],
            "false_rejection_rate": item["false_rejection_rate"]["value"],
            "package_complete_accuracy": item["package_complete_accuracy"]["value"],
            "safety_macro_f1": item["safety_macro_f1"], "failure_case_count": item["failure_case_count"],
        })
    _write_csv(OUTPUT / "metrics_summary.csv", metric_rows)
    _write_csv(OUTPUT / "latency_summary.csv", latency_rows)

    full_metrics = next(item for item in system_metric_data if item["system_id"] == "full_system")
    confusion_rows = []
    for actual, predictions in full_metrics["confusion_matrix"].items():
        confusion_rows.append({"actual_status": actual, **predictions})
    _write_csv(OUTPUT / "confusion_matrix.csv", confusion_rows)
    _write_json(OUTPUT / "failure_cases.json", {"metadata": metadata, "case_count": len(failures), "cases": failures})
    metric_audit = build_metric_audit(full, annotations)
    _write_json(OUTPUT / "metric_audit.json", metric_audit)
    _write_csv(OUTPUT / "metric_audit.csv", metric_audit_csv_rows(metric_audit))
    (OUTPUT / "metric_audit.md").write_text(metric_audit_markdown(metric_audit), encoding="utf-8")

    figures = generate_figures(OUTPUT / "figures", system_metric_data, ablation_metric_data, full_metrics["confusion_matrix"], latency_rows, failures, reliability, manifest.sample_count)
    false_rejections = [item for item in full if item.false_rejection]
    coverage_analysis = {
        "false_rejections": len(false_rejections),
        "confidence_recaptures": sum(item.predicted_safety_status.value == "RECAPTURE_REQUIRED" and annotations[item.sample_id].expected_safety_status.value == "READY_TO_CONFIRM" for item in false_rejections),
        "provider_faults": sum(annotations[item.sample_id].fault_plan != "NONE" for item in false_rejections),
    }
    report = evaluation_report_markdown(manifest.sample_count, manifest.category_counts, system_metric_data, ablation_metric_data, reliability, latency_rows, len(failures), coverage_analysis)
    (OUTPUT / "evaluation_report.md").write_text(report, encoding="utf-8")
    competition_report = report.replace("# GlanceFlow Stage 5 自动评测报告", "# 初赛评测结果", 1)
    competition_report += "\n## 图表\n\n七张图表位于 `outputs/evaluation/figures/`，全部由本次运行结果生成。\n"
    competition_path = Path("docs/competition/evaluation-results.md")
    competition_path.parent.mkdir(parents=True, exist_ok=True)
    competition_path.write_text(competition_report, encoding="utf-8")
    image_total_latency = next(
        row for row in latency_rows
        if row["system_id"] == "full_system" and row["input_type"] == "IMAGE" and row["stage"] == "total_ms"
    )
    video_total_latency = next(
        row for row in latency_rows
        if row["system_id"] == "full_system" and row["input_type"] == "VIDEO" and row["stage"] == "total_ms"
    )
    scorecard = {
        "generated_at": metadata["generated_at"], "source": "programmatic_stage5_evaluation",
        "erroneous_execution_rate": full_metrics["erroneous_execution_rate"],
        "valid_coverage_rate": full_metrics["valid_coverage_rate"],
        "false_rejection_rate": full_metrics["false_rejection_rate"],
        "package_complete_accuracy": full_metrics["package_complete_accuracy"],
        "readback_consistency_rate": reliability["readback_consistency_rate"],
        "rollback_success_rate": reliability["rollback_success_rate"],
        "undo_success_rate": reliability["undo_success_rate"],
        "image_median_end_to_end_latency_ms": round(image_total_latency["median_ms"], 3),
        "video_median_end_to_end_latency_ms": round(video_total_latency["median_ms"], 3),
        "sample_count": manifest.sample_count,
        "environment": metadata["environment"], "real_glasses": False,
    }
    _write_json(OUTPUT / "final_scorecard.json", scorecard)
    (OUTPUT / "final_scorecard.md").write_text(final_scorecard_markdown(scorecard), encoding="utf-8")
    return {
        "metadata": metadata, "system_metrics": system_metric_data,
        "ablation_metrics": ablation_metric_data, "reliability": reliability,
        "figure_paths": [str(path) for path in figures], "failure_case_count": len(failures),
    }


def main() -> int:
    result = run_all()
    print(f"Stage 5 评测完成：n={result['metadata']['sample_count']}，图表={len(result['figure_paths'])}，失败案例={result['failure_case_count']}")
    for item in result["system_metrics"]:
        print(f"  {item['system_id']}: 错误执行={item['erroneous_execution_rate']['display']} 覆盖={item['valid_coverage_rate']['display']} 误拒={item['false_rejection_rate']['display']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
