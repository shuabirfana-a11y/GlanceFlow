from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

import numpy as np

from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.evaluation.models import EvaluationAnnotation, MetricValue, StageLatencies, SystemMetrics, SystemResult


STATUSES = tuple(status.value for status in SafetyGateStatus)


def ratio(numerator: int, denominator: int) -> MetricValue:
    if denominator == 0:
        return MetricValue(value=None, numerator=numerator, denominator=denominator, display="N/A")
    value = numerator / denominator
    return MetricValue(value=value, numerator=numerator, denominator=denominator, display=f"{value * 100:.2f}%")


def compute_system_metrics(results: list[SystemResult], annotations: dict[str, EvaluationAnnotation]) -> SystemMetrics:
    if not results:
        raise ValueError("至少需要一条系统结果。")
    system_ids = {result.system_id for result in results}
    if len(system_ids) != 1:
        raise ValueError("一次只能计算一个系统的指标。")
    actual_executions = sum(result.executed for result in results)
    erroneous = sum(result.erroneous_execution for result in results)
    expected_executable = sum(annotations[result.sample_id].is_executable for result in results)
    correct = sum(result.correct_execution for result in results)
    false_rejections = sum(result.false_rejection for result in results)

    confusion = {expected: {predicted: 0 for predicted in STATUSES} for expected in STATUSES}
    for result in results:
        expected = annotations[result.sample_id].expected_safety_status.value
        confusion[expected][result.predicted_safety_status.value] += 1
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values = []
    for label in STATUSES:
        tp = confusion[label][label]
        fp = sum(confusion[expected][label] for expected in STATUSES if expected != label)
        fn = sum(confusion[label][predicted] for predicted in STATUSES if predicted != label)
        support = sum(confusion[label].values())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    return SystemMetrics(
        system_id=next(iter(system_ids)), sample_count=len(results),
        erroneous_execution_rate=ratio(erroneous, actual_executions),
        valid_coverage_rate=ratio(correct, expected_executable),
        false_rejection_rate=ratio(false_rejections, expected_executable),
        package_complete_accuracy=ratio(sum(result.package_completely_correct for result in results), expected_executable),
        safety_macro_f1=mean(f1_values), per_class=per_class, confusion_matrix=confusion,
        failure_case_count=sum(result.erroneous_execution or result.false_rejection or annotations[result.sample_id].expected_safety_status != result.predicted_safety_status for result in results),
    )


def latency_statistics(results: list[SystemResult]) -> list[dict]:
    stages = tuple(StageLatencies.model_fields) if results else ()
    rows = []
    for stage in stages:
        values = [float(getattr(result.latencies, stage)) for result in results]
        rows.append({
            "system_id": results[0].system_id,
            "stage": stage,
            "sample_count": len(values),
            "mean_ms": mean(values),
            "median_ms": median(values),
            "p90_ms": float(np.percentile(values, 90)),
            "min_ms": min(values),
            "max_ms": max(values),
        })
    return rows


def group_results(results: list[SystemResult]) -> dict[str, list[SystemResult]]:
    grouped: dict[str, list[SystemResult]] = defaultdict(list)
    for result in results:
        grouped[result.system_id].append(result)
    return dict(grouped)
