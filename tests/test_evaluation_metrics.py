from pathlib import Path

from glanceflow.domain.enums import NoticeType, SafetyGateStatus
from glanceflow.evaluation.metrics import compute_system_metrics, latency_statistics, ratio
from glanceflow.evaluation.models import EvaluationAnnotation, MediaType, SourceType, StageLatencies, SystemResult


def annotation(sample_id, *, executable, status=SafetyGateStatus.READY_TO_CONFIRM):
    return EvaluationAnnotation(
        sample_id=sample_id,input_path=Path("synthetic.png"),media_type=MediaType.IMAGE,
        source_type=SourceType.ARTIFICIAL_POSTER,category="test",expected_notice_type=NoticeType.EVENT_NOTICE,
        expected_title="活动",expected_event_start="2026-08-07T14:00:00+08:00",expected_location="报告厅",
        expected_deadline=None,expected_safety_status=status,expected_failure_reason=None,is_executable=executable,
        scenario_tags=["test"],synthetic=True,annotation_notes="测试指标公式。",
    )


def result(sample_id, *, executed=False, correct=False, false_rejection=False, erroneous=False, status=SafetyGateStatus.READY_TO_CONFIRM, latency=1):
    return SystemResult(
        sample_id=sample_id,system_id="system",predicted_safety_status=status,executed=executed,
        active_event_count=int(executed),fields_match=correct,correct_execution=correct,
        erroneous_execution=erroneous,false_rejection=false_rejection,package_completely_correct=correct,
        latencies=StageLatencies(total_ms=latency),
    )


def test_metric_formulas_count_error_rejection_and_complete_package():
    annotations={
        "GF-EVAL-001":annotation("GF-EVAL-001",executable=True),
        "GF-EVAL-002":annotation("GF-EVAL-002",executable=True),
        "GF-EVAL-003":annotation("GF-EVAL-003",executable=False,status=SafetyGateStatus.CONTRADICTION_BLOCKED),
    }
    results=[
        result("GF-EVAL-001",executed=True,correct=True),
        result("GF-EVAL-002",false_rejection=True),
        result("GF-EVAL-003",executed=True,erroneous=True,status=SafetyGateStatus.READY_TO_CONFIRM),
    ]
    metrics=compute_system_metrics(results,annotations)
    assert metrics.erroneous_execution_rate.value == .5
    assert metrics.valid_coverage_rate.value == .5
    assert metrics.false_rejection_rate.value == .5
    assert metrics.package_complete_accuracy.value == .5


def test_all_reject_cannot_earn_high_coverage():
    annotations={"GF-EVAL-001":annotation("GF-EVAL-001",executable=True)}
    metrics=compute_system_metrics([result("GF-EVAL-001",false_rejection=True)],annotations)
    assert metrics.erroneous_execution_rate.value is None
    assert metrics.erroneous_execution_rate.display == "N/A"
    assert metrics.valid_coverage_rate.value == 0
    assert metrics.false_rejection_rate.value == 1


def test_zero_denominator_is_na_not_zero_or_one():
    metric=ratio(0,0)
    assert metric.value is None and metric.display == "N/A"


def test_confusion_matrix_and_macro_f1_are_programmatic():
    annotations={
        "GF-EVAL-001":annotation("GF-EVAL-001",executable=True),
        "GF-EVAL-002":annotation("GF-EVAL-002",executable=False,status=SafetyGateStatus.NEED_USER_INPUT),
    }
    metrics=compute_system_metrics([
        result("GF-EVAL-001"),result("GF-EVAL-002",status=SafetyGateStatus.RECAPTURE_REQUIRED)
    ],annotations)
    assert metrics.confusion_matrix["READY_TO_CONFIRM"]["READY_TO_CONFIRM"] == 1
    assert metrics.confusion_matrix["NEED_USER_INPUT"]["RECAPTURE_REQUIRED"] == 1
    assert 0 <= metrics.safety_macro_f1 <= 1


def test_latency_statistics_include_mean_median_p90_min_max():
    rows=latency_statistics([result("GF-EVAL-001",latency=1),result("GF-EVAL-002",latency=3)])
    total=next(row for row in rows if row["stage"] == "total_ms")
    assert total["mean_ms"] == 2
    assert total["median_ms"] == 2
    assert total["min_ms"] == 1
    assert total["max_ms"] == 3
    assert total["p90_ms"] > 2
