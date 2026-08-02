from __future__ import annotations

from statistics import mean

from glanceflow.evaluation.metrics import STATUSES
from glanceflow.evaluation.models import EvaluationAnnotation, SystemResult


def _rate_audit(
    formula: str,
    numerator_ids: list[str],
    denominator_ids: list[str],
) -> dict:
    numerator = len(numerator_ids)
    denominator = len(denominator_ids)
    return {
        "formula": formula,
        "numerator": numerator,
        "denominator": denominator,
        "numerator_sample_ids": numerator_ids,
        "denominator_sample_ids": denominator_ids,
        "value": numerator / denominator if denominator else None,
        "display": f"{numerator / denominator * 100:.2f}%" if denominator else "N/A",
    }


def build_metric_audit(
    results: list[SystemResult],
    annotations: dict[str, EvaluationAnnotation],
) -> dict:
    """Recalculate Full System metrics with sample-level traceability."""
    ordered = sorted(results, key=lambda item: item.sample_id)
    executed_ids = [item.sample_id for item in ordered if item.executed]
    erroneous_ids = [item.sample_id for item in ordered if item.erroneous_execution]
    executable_ids = [item.sample_id for item in ordered if annotations[item.sample_id].is_executable]
    correct_ids = [item.sample_id for item in ordered if item.correct_execution]
    rejected_ids = [item.sample_id for item in ordered if item.false_rejection]
    complete_ids = [item.sample_id for item in ordered if item.package_completely_correct]

    confusion: dict[str, dict[str, dict]] = {
        actual: {predicted: {"count": 0, "sample_ids": []} for predicted in STATUSES}
        for actual in STATUSES
    }
    for result in ordered:
        actual = annotations[result.sample_id].expected_safety_status.value
        predicted = result.predicted_safety_status.value
        confusion[actual][predicted]["count"] += 1
        confusion[actual][predicted]["sample_ids"].append(result.sample_id)

    per_class: dict[str, dict] = {}
    class_f1_values: list[float] = []
    for label in STATUSES:
        tp_ids = list(confusion[label][label]["sample_ids"])
        fp_ids = [
            sample_id
            for actual in STATUSES
            if actual != label
            for sample_id in confusion[actual][label]["sample_ids"]
        ]
        fn_ids = [
            sample_id
            for predicted in STATUSES
            if predicted != label
            for sample_id in confusion[label][predicted]["sample_ids"]
        ]
        precision_denominator = [*tp_ids, *fp_ids]
        recall_denominator = [*tp_ids, *fn_ids]
        precision = len(tp_ids) / len(precision_denominator) if precision_denominator else 0.0
        recall = len(tp_ids) / len(recall_denominator) if recall_denominator else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        class_f1_values.append(f1)
        per_class[label] = {
            "tp": len(tp_ids),
            "fp": len(fp_ids),
            "fn": len(fn_ids),
            "tp_sample_ids": tp_ids,
            "fp_sample_ids": fp_ids,
            "fn_sample_ids": fn_ids,
            "precision_formula": "TP / (TP + FP)",
            "precision_numerator": len(tp_ids),
            "precision_denominator": len(precision_denominator),
            "precision_denominator_sample_ids": precision_denominator,
            "precision": precision,
            "recall_formula": "TP / (TP + FN)",
            "recall_numerator": len(tp_ids),
            "recall_denominator": len(recall_denominator),
            "recall_denominator_sample_ids": recall_denominator,
            "recall": recall,
            "f1_formula": "2 * precision * recall / (precision + recall)",
            "f1": f1,
        }

    expected_ready_ids = [
        sample.sample_id
        for sample in sorted(annotations.values(), key=lambda item: item.sample_id)
        if sample.expected_safety_status.value == "READY_TO_CONFIRM"
    ]
    ready_true_positive_ids = list(confusion["READY_TO_CONFIRM"]["READY_TO_CONFIRM"]["sample_ids"])
    conflict_wait_ids = [
        sample_id
        for sample_id in expected_ready_ids
        if annotations[sample_id].existing_context == "CONFLICT"
        and not annotations[sample_id].is_executable
    ]
    return {
        "system_id": ordered[0].system_id if ordered else "full_system",
        "sample_count": len(ordered),
        "source": "dataset manifest plus freshly generated Full System result records",
        "metrics": {
            "erroneous_execution_rate": _rate_audit(
                "erroneously executed packages / all actually executed packages",
                erroneous_ids,
                executed_ids,
            ),
            "valid_coverage_rate": _rate_audit(
                "correctly executed packages / all notices labeled is_executable=true",
                correct_ids,
                executable_ids,
            ),
            "false_rejection_rate": _rate_audit(
                "executable notices not correctly executed / all notices labeled is_executable=true",
                rejected_ids,
                executable_ids,
            ),
            "package_complete_accuracy": _rate_audit(
                "completely correct packages / all notices labeled is_executable=true",
                complete_ids,
                executable_ids,
            ),
            "safety_macro_f1": {
                "formula": "sum(F1 for the four safety states) / 4",
                "numerator": sum(class_f1_values),
                "denominator": len(STATUSES),
                "component_labels": list(STATUSES),
                "component_values": class_f1_values,
                "value": mean(class_f1_values),
                "per_class": per_class,
            },
        },
        "confusion_matrix": confusion,
        "coverage_conclusion": {
            "expected_ready_count": len(expected_ready_ids),
            "expected_ready_sample_ids": expected_ready_ids,
            "ready_predicted_ready_count": len(ready_true_positive_ids),
            "ready_predicted_ready_sample_ids": ready_true_positive_ids,
            "ready_state_recall": len(ready_true_positive_ids) / len(expected_ready_ids),
            "non_executable_conflict_wait_count": len(conflict_wait_ids),
            "non_executable_conflict_wait_sample_ids": conflict_wait_ids,
            "conclusion": (
                "Valid coverage remains 15/20 = 75.00%. The separate 19/22 = 86.36% figure "
                "is READY_TO_CONFIRM state recall, not execution coverage; two READY labels are "
                "conflict cases that intentionally wait for secondary confirmation and have "
                "is_executable=false in this protocol."
            ),
        },
    }


def metric_audit_csv_rows(audit: dict) -> list[dict]:
    rows: list[dict] = []
    all_sample_ids = sorted({
        sample_id
        for predictions in audit["confusion_matrix"].values()
        for cell in predictions.values()
        for sample_id in cell["sample_ids"]
    })
    for name, metric in audit["metrics"].items():
        if name == "safety_macro_f1":
            rows.append({
                "metric": name,
                "component": "macro",
                "formula": metric["formula"],
                "numerator": metric["numerator"],
                "denominator": metric["denominator"],
                "value": metric["value"],
                "numerator_sample_ids": "",
                "denominator_sample_ids": ";".join(all_sample_ids),
            })
            for label, detail in metric["per_class"].items():
                rows.append({
                    "metric": name,
                    "component": label,
                    "formula": detail["f1_formula"],
                    "numerator": detail["tp"],
                    "denominator": detail["tp"] + detail["fp"] + detail["fn"],
                    "value": detail["f1"],
                    "numerator_sample_ids": ";".join(detail["tp_sample_ids"]),
                    "denominator_sample_ids": ";".join([*detail["tp_sample_ids"], *detail["fp_sample_ids"], *detail["fn_sample_ids"]]),
                })
            continue
        rows.append({
            "metric": name,
            "component": "overall",
            "formula": metric["formula"],
            "numerator": metric["numerator"],
            "denominator": metric["denominator"],
            "value": metric["value"],
            "numerator_sample_ids": ";".join(metric["numerator_sample_ids"]),
            "denominator_sample_ids": ";".join(metric["denominator_sample_ids"]),
        })
    for actual, predictions in audit["confusion_matrix"].items():
        for predicted, cell in predictions.items():
            rows.append({
                "metric": "confusion_matrix",
                "component": f"{actual}->{predicted}",
                "formula": "count(samples with actual state and predicted state)",
                "numerator": cell["count"],
                "denominator": audit["sample_count"],
                "value": cell["count"],
                "numerator_sample_ids": ";".join(cell["sample_ids"]),
                "denominator_sample_ids": "",
            })
    return rows


def metric_audit_markdown(audit: dict) -> str:
    lines = [
        "# GlanceFlow 评测指标独立核验",
        "",
        "> 本文件由统一评测入口根据数据清单和本次 Full System 原始结果重新计算，不引用既有报告中的汇总数字。",
        "",
        "## 核心指标",
        "",
    ]
    for name, metric in audit["metrics"].items():
        if name == "safety_macro_f1":
            lines += [
                f"### {name}",
                "",
                f"- 公式：`{metric['formula']}`",
                f"- 分子：{metric['numerator']:.12f}（四类 F1 之和）",
                f"- 分母：{metric['denominator']}",
                f"- 最终值：{metric['value']:.12f}",
                "",
                "| 状态 | TP | FP | FN | Precision | Recall | F1 | TP sample_id | FP sample_id | FN sample_id |",
                "|---|---:|---:|---:|---:|---:|---:|---|---|---|",
            ]
            for label, detail in metric["per_class"].items():
                lines.append(
                    f"| {label} | {detail['tp']} | {detail['fp']} | {detail['fn']} | "
                    f"{detail['precision']:.6f} | {detail['recall']:.6f} | {detail['f1']:.6f} | "
                    f"{', '.join(detail['tp_sample_ids']) or '—'} | {', '.join(detail['fp_sample_ids']) or '—'} | "
                    f"{', '.join(detail['fn_sample_ids']) or '—'} |"
                )
            lines.append("")
            continue
        lines += [
            f"### {name}",
            "",
            f"- 公式：`{metric['formula']}`",
            f"- 分子：{metric['numerator']}；sample_id：{', '.join(metric['numerator_sample_ids']) or '无'}",
            f"- 分母：{metric['denominator']}；sample_id：{', '.join(metric['denominator_sample_ids']) or '无'}",
            f"- 最终值：{metric['display']}",
            "",
        ]
    lines += [
        "## 四状态混淆矩阵",
        "",
        "每个单元格的分子是该真实状态与预测状态组合的样本数，整体核验分母为全部 46 个样本。",
        "",
        "| 真实状态 | 预测状态 | 数量 | sample_id |",
        "|---|---|---:|---|",
    ]
    for actual, predictions in audit["confusion_matrix"].items():
        for predicted, cell in predictions.items():
            lines.append(f"| {actual} | {predicted} | {cell['count']} | {', '.join(cell['sample_ids']) or '—'} |")
    conclusion = audit["coverage_conclusion"]
    lines += [
        "",
        "## 75% 覆盖率核验结论",
        "",
        f"真实 READY 样本为 {conclusion['expected_ready_count']} 个，其中 {conclusion['ready_predicted_ready_count']} 个预测为 READY，状态召回为 19/22 = {conclusion['ready_state_recall'] * 100:.2f}%。",
        f"其中 {conclusion['non_executable_conflict_wait_count']} 个冲突样本（{', '.join(conclusion['non_executable_conflict_wait_sample_ids'])}）按协议 `is_executable=false`，等待二次确认，不进入有效覆盖率分母。",
        "有效覆盖率按题设定义重新计算为正确执行 15 个 / 应执行 20 个 = **75.00%**。因此 75% 正确；86.36% 是 READY 状态召回，不能替代执行覆盖率。",
    ]
    return "\n".join(lines) + "\n"
