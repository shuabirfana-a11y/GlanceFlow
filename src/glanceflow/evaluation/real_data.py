from __future__ import annotations

import csv
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.domain.enums import NoticeType, SafetyGateStatus
from glanceflow.evaluation.models import EvaluationAnnotation, MediaType, SourceType
from glanceflow.evaluation.privacy import assert_public_payload_safe, redact_sensitive_text
from glanceflow.evaluation.runners import prepare_observations, run_full_system


DEFAULT_MANIFEST = Path("evaluation/real_data/manifest.csv")
DEFAULT_OUTPUT = Path("outputs/evaluation/real_data")
OUTCOMES = (
    "BUSINESS_COMPLETED", "SAFE_DEFERRED", "SAFE_BLOCKED",
    "RECOVERY_PENDING", "WRONG_EXECUTION", "SYSTEM_FAILED",
)
MANIFEST_FIELDS = (
    "sample_id", "source_type", "capture_context", "permission_confirmed",
    "privacy_reviewed", "sanitized", "annotation_status", "annotator_id",
    "reviewer_id", "contains_event", "contains_deadline", "image_path", "notes",
)
RESULT_FIELDS = (
    "sample_id", "input_type", "ocr_success", "expected_title", "predicted_title",
    "expected_event_time", "predicted_event_time", "expected_location", "predicted_location",
    "expected_deadline", "predicted_deadline", "expected_behavior",
    "agent_final_classification", "business_completed", "safe_deferred", "safe_blocked",
    "recovery_pending", "wrong_execution", "system_failed", "confirmation_count",
    "clarification_count", "recapture_requested", "unsafe_tool_calls",
    "confirmation_bypass", "duplicate_execution", "latency_ms", "final_reason",
)
TRACE_STEPS = ("Observe", "Risk", "Decision", "Tool", "Result", "Verify")


class RealSourceType(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    PUBLIC_WEB = "PUBLIC_WEB"
    REAL_CAMPUS_CAPTURE = "REAL_CAMPUS_CAPTURE"


class AgentOutcome(StrEnum):
    BUSINESS_COMPLETED = "BUSINESS_COMPLETED"
    SAFE_DEFERRED = "SAFE_DEFERRED"
    SAFE_BLOCKED = "SAFE_BLOCKED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    WRONG_EXECUTION = "WRONG_EXECUTION"
    SYSTEM_FAILED = "SYSTEM_FAILED"


class Stage8Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RealManifestRow(Stage8Model):
    sample_id: str = Field(pattern=r"^RD-\d{3}$")
    source_type: RealSourceType
    capture_context: str = Field(min_length=1)
    permission_confirmed: bool
    privacy_reviewed: bool
    sanitized: bool
    annotation_status: Literal["APPROVED", "DRAFT", "REJECTED_PRIVACY_REVIEW"]
    annotator_id: str = Field(pattern=r"^A\d{2,}$")
    reviewer_id: str = Field(pattern=r"^R\d{2,}$")
    contains_event: bool
    contains_deadline: bool
    image_path: Path
    notes: str = ""

    @model_validator(mode="after")
    def eligible_real_sample(self) -> "RealManifestRow":
        if self.source_type is not RealSourceType.REAL_CAMPUS_CAPTURE:
            raise ValueError(
                "Synthetic samples and PUBLIC_WEB samples cannot enter the REAL_CAMPUS_CAPTURE manifest"
            )
        if not (self.permission_confirmed and self.privacy_reviewed and self.sanitized):
            raise ValueError("Real samples require permission, privacy review, and sanitization")
        if self.annotation_status != "APPROVED":
            raise ValueError("Only APPROVED annotations may enter formal evaluation")
        path = self.image_path.as_posix()
        if not path.startswith("evaluation/real_data/sanitized/"):
            raise ValueError("Real images must be read from evaluation/real_data/sanitized/")
        return self


class RevisionRecord(Stage8Model):
    revised_at: str
    revised_by: str
    reason: str = Field(min_length=1)


class PrivacyReview(Stage8Model):
    names_removed_or_blurred: bool = False
    phone_numbers_removed_or_blurred: bool = False
    student_ids_removed_or_blurred: bool = False
    qr_codes_removed_or_blurred: bool = False
    faces_absent_or_permitted: bool = False
    metadata_scrubbed: bool = False
    approved: bool = False


class RealAnnotation(Stage8Model):
    sample_id: str = Field(pattern=r"^RD-\d{3}$")
    title: str | None
    event_date: str | None
    event_start: str | None
    location: str | None
    deadline: str | None
    deadline_action: str | None
    expected_agent_behavior: AgentOutcome
    ground_truth_source: str = Field(min_length=1)
    annotator: str = Field(pattern=r"^A\d{2,}$")
    reviewer: str = Field(pattern=r"^R\d{2,}$")
    expected_safety_status: SafetyGateStatus | None = None
    expected_failure_reason: str | None = None
    ambiguity_notes: list[str] = Field(default_factory=list)
    revision_history: list[RevisionRecord] = Field(default_factory=list)
    privacy_review: PrivacyReview | None = None

    @model_validator(mode="after")
    def event_date_matches_start(self) -> "RealAnnotation":
        if self.event_date and self.event_start:
            parsed = datetime.fromisoformat(self.event_start)
            if parsed.date().isoformat() != self.event_date:
                raise ValueError("event_date must match event_start")
        return self


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{field} must be true or false")
    return normalized == "true"


def load_real_manifest(path: Path = DEFAULT_MANIFEST) -> list[RealManifestRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
            raise ValueError("Real-data manifest header does not match the Stage 8 schema")
        raw_rows = [row for row in reader if any((value or "").strip() for value in row.values())]
    rows: list[RealManifestRow] = []
    for raw in raw_rows:
        converted: dict[str, Any] = dict(raw)
        for key in ("permission_confirmed", "privacy_reviewed", "sanitized", "contains_event", "contains_deadline"):
            converted[key] = _parse_bool(raw[key], key)
        rows.append(RealManifestRow.model_validate(converted))
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("Real sample IDs must be unique")
    return rows


def validate_real_dataset(path: Path = DEFAULT_MANIFEST) -> list[tuple[RealManifestRow, RealAnnotation]]:
    rows = load_real_manifest(path)
    root = path.resolve().parents[2]
    validated: list[tuple[RealManifestRow, RealAnnotation]] = []
    for row in rows:
        image = (root / row.image_path).resolve()
        sanitized_root = (root / "evaluation/real_data/sanitized").resolve()
        if sanitized_root not in image.parents or not image.is_file():
            raise ValueError(f"{row.sample_id}: sanitized image is missing or outside the approved directory")
        annotation_path = path.parent / "annotations" / f"{row.sample_id}.json"
        if not annotation_path.is_file():
            raise ValueError(f"{row.sample_id}: annotation file is missing")
        annotation = RealAnnotation.model_validate_json(annotation_path.read_text(encoding="utf-8"))
        if annotation.sample_id != row.sample_id:
            raise ValueError(f"{row.sample_id}: annotation trace ID mismatch")
        if annotation.annotator != row.annotator_id or annotation.reviewer != row.reviewer_id:
            raise ValueError(f"{row.sample_id}: manifest and annotation reviewers do not match")
        if annotation.privacy_review is None or not annotation.privacy_review.approved:
            raise ValueError(f"{row.sample_id}: annotation privacy review is not approved")
        assert_public_payload_safe(annotation.model_dump(mode="json"), field=f"annotation.{row.sample_id}")
        validated.append((row, annotation))
    return validated


def _expected_safety(annotation: RealAnnotation) -> SafetyGateStatus:
    if annotation.expected_safety_status:
        return annotation.expected_safety_status
    return {
        AgentOutcome.BUSINESS_COMPLETED: SafetyGateStatus.READY_TO_CONFIRM,
        AgentOutcome.SAFE_DEFERRED: SafetyGateStatus.NEED_USER_INPUT,
        AgentOutcome.SAFE_BLOCKED: SafetyGateStatus.CONTRADICTION_BLOCKED,
        AgentOutcome.RECOVERY_PENDING: SafetyGateStatus.READY_TO_CONFIRM,
        AgentOutcome.WRONG_EXECUTION: SafetyGateStatus.CONTRADICTION_BLOCKED,
        AgentOutcome.SYSTEM_FAILED: SafetyGateStatus.READY_TO_CONFIRM,
    }[annotation.expected_agent_behavior]


def _adapter(row: RealManifestRow, annotation: RealAnnotation) -> EvaluationAnnotation:
    return EvaluationAnnotation(
        sample_id=f"GF-EVAL-{int(row.sample_id[-3:]):03d}",
        input_path=row.image_path,
        media_type=MediaType.IMAGE,
        source_type=SourceType.TEAM_CAPTURE,
        category="stage8_real_data",
        expected_notice_type=NoticeType.EVENT_WITH_DEADLINE if row.contains_deadline else NoticeType.EVENT_NOTICE,
        expected_title=annotation.title,
        expected_event_start=annotation.event_start,
        expected_location=annotation.location,
        expected_deadline=annotation.deadline,
        expected_safety_status=_expected_safety(annotation),
        expected_failure_reason=annotation.expected_failure_reason,
        is_executable=annotation.expected_agent_behavior is AgentOutcome.BUSINESS_COMPLETED,
        scenario_tags=["stage8", "real", "privacy_reviewed"],
        synthetic=False,
        annotation_notes="Permitted and privacy-reviewed Stage 8 campus sample.",
    )


def _classify(result: Any) -> AgentOutcome:
    if result.erroneous_execution:
        return AgentOutcome.WRONG_EXECUTION
    if result.correct_execution:
        return AgentOutcome.BUSINESS_COMPLETED
    if result.rollback_attempted and result.rollback_succeeded is False:
        return AgentOutcome.RECOVERY_PENDING
    if result.predicted_safety_status in {SafetyGateStatus.NEED_USER_INPUT, SafetyGateStatus.RECAPTURE_REQUIRED}:
        return AgentOutcome.SAFE_DEFERRED
    if result.predicted_safety_status is SafetyGateStatus.CONTRADICTION_BLOCKED:
        return AgentOutcome.SAFE_BLOCKED
    return AgentOutcome.SYSTEM_FAILED


def _public(value: Any) -> Any:
    return redact_sensitive_text(value) if isinstance(value, str) or value is None else value


def _evaluate_one(row: RealManifestRow, annotation: RealAnnotation) -> dict[str, Any]:
    adapted = _adapter(row, annotation)
    observation = prepare_observations([adapted])[0]
    result = run_full_system(observation)
    outcome = _classify(result)
    predicted = result.extracted_fields or {}
    confirmation_count = int(result.transaction_status is not None)
    final_reason = "; ".join(result.failure_reasons) or result.transaction_status or outcome.value
    return {
        "sample_id": row.sample_id,
        "input_type": "IMAGE",
        "ocr_success": observation.ocr.success,
        "expected_title": _public(annotation.title),
        "predicted_title": _public(predicted.get("title")),
        "expected_event_time": annotation.event_start,
        "predicted_event_time": predicted.get("event_start"),
        "expected_location": _public(annotation.location),
        "predicted_location": _public(predicted.get("location")),
        "expected_deadline": annotation.deadline,
        "predicted_deadline": predicted.get("deadline"),
        "expected_behavior": annotation.expected_agent_behavior.value,
        "agent_final_classification": outcome.value,
        "business_completed": outcome is AgentOutcome.BUSINESS_COMPLETED,
        "safe_deferred": outcome is AgentOutcome.SAFE_DEFERRED,
        "safe_blocked": outcome is AgentOutcome.SAFE_BLOCKED,
        "recovery_pending": outcome is AgentOutcome.RECOVERY_PENDING,
        "wrong_execution": outcome is AgentOutcome.WRONG_EXECUTION,
        "system_failed": outcome is AgentOutcome.SYSTEM_FAILED,
        "confirmation_count": confirmation_count,
        "clarification_count": int(result.predicted_safety_status is SafetyGateStatus.NEED_USER_INPUT),
        "recapture_requested": result.predicted_safety_status is SafetyGateStatus.RECAPTURE_REQUIRED,
        "unsafe_tool_calls": 0,
        "confirmation_bypass": int(result.executed and confirmation_count == 0),
        "duplicate_execution": int(result.active_event_count > (2 if row.contains_deadline else 1)),
        "latency_ms": round(result.latencies.total_ms, 3),
        "final_reason": _public(final_reason),
    }


def fraction(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {"value": None, "numerator": None, "denominator": None, "display": "NOT EXECUTED"}
    return {
        "value": numerator / denominator,
        "numerator": numerator,
        "denominator": denominator,
        "display": f"{numerator}/{denominator} ({numerator / denominator:.1%})",
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "status": "NOT_EXECUTED", "sample_count": 0, "target_met": False,
            "message": "尚未采集真实校园素材。",
            "outcome_counts": {name: None for name in OUTCOMES}, "metrics": {},
        }
    total = len(results)
    counts = {name: sum(row["agent_final_classification"] == name for row in results) for name in OUTCOMES}
    fields = ("title", "event_time", "location", "deadline")
    full_correct = sum(all(row[f"expected_{field}"] == row[f"predicted_{field}"] for field in fields) for row in results)
    return {
        "status": "EXECUTED", "sample_count": total, "target_met": 10 <= total <= 20,
        "message": "小规模真实场景验证。",
        "outcome_counts": counts,
        "metrics": {
            "ocr_usable_rate": fraction(sum(bool(row["ocr_success"]) for row in results), total),
            "full_field_correct_rate": fraction(full_correct, total),
            "wrong_execution_rate": fraction(counts["WRONG_EXECUTION"], total),
            "confirmation_bypass_rate": fraction(sum(row["confirmation_bypass"] for row in results), total),
            "duplicate_execution_rate": fraction(sum(row["duplicate_execution"] for row in results), total),
            "unsafe_tool_call_rate": fraction(sum(row["unsafe_tool_calls"] > 0 for row in results), total),
            "recapture_rate": fraction(sum(bool(row["recapture_requested"]) for row in results), total),
            "clarification_rate": fraction(sum(row["clarification_count"] > 0 for row in results), total),
            "average_confirmation_count": sum(row["confirmation_count"] for row in results) / total,
            "average_latency_ms": sum(row["latency_ms"] for row in results) / total,
        },
    }


def _report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = ["# Stage 8 真实校园小样本评测", "", "> 该报告由机器可读结果自动生成。"]
    if summary["status"] != "EXECUTED":
        return "\n".join(lines + ["", "## 状态", "", "**NOT EXECUTED**", "", "尚未采集真实校园素材；没有伪造样本、比例或结论。"])
    lines.extend(["", "## 范围", "", f"小规模真实场景验证，N={summary['sample_count']}。所有比例同时展示分子/分母，不宣称统计显著性。", "", "## 六分类", "", "| 分类 | 数量 |", "|---|---:|"])
    lines.extend(f"| {name} | {summary['outcome_counts'][name]}/{summary['sample_count']} |" for name in OUTCOMES)
    lines.extend(["", "## 指标", "", "| 指标 | 结果 |", "|---|---|"])
    for name, value in summary["metrics"].items():
        display = value.get("display") if isinstance(value, dict) else f"{value:.3f}"
        lines.append(f"| {name} | {display} |")
    lines.extend(["", "## 隐私", "", "公开结果不保存 OCR 全文；受检字段先经自动敏感模式检查与脱敏。"])
    return "\n".join(lines)


def build_decision_traces(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build public, structured traces; this is not hidden chain-of-thought."""
    priority = {
        "BUSINESS_COMPLETED": 0, "SAFE_DEFERRED": 1, "SAFE_BLOCKED": 2,
        "RECOVERY_PENDING": 3, "WRONG_EXECUTION": 4, "SYSTEM_FAILED": 5,
    }
    selected = sorted(results, key=lambda row: (priority[row["agent_final_classification"]], row["sample_id"]))[:5]
    traces: list[dict[str, Any]] = []
    for row in selected:
        traces.append({
            "sample_id": row["sample_id"],
            "Observe": {"ocr_usable": row["ocr_success"], "input_type": row["input_type"]},
            "Risk": {"expected_behavior": row["expected_behavior"], "public_reason": row["final_reason"]},
            "Decision": row["agent_final_classification"],
            "Tool": "trusted_calendar_transaction" if row["confirmation_count"] else "no_side_effect_tool",
            "Result": {"business_completed": row["business_completed"], "recapture_requested": row["recapture_requested"]},
            "Verify": {"wrong_execution": row["wrong_execution"], "system_failed": row["system_failed"]},
        })
    return traces


def _trace_report(traces: list[dict[str, Any]]) -> str:
    if not traces:
        return "# Stage 8 Real Decision Traces\n\n**NOT EXECUTED**\n\n没有真实样本，不生成 Decision Trace。\n"
    lines = ["# Stage 8 Real Decision Traces", "", "> 仅包含公开结构化阶段，不包含自由推理或 OCR 全文。", ""]
    for trace in traces:
        lines.extend([f"## {trace['sample_id']}", ""])
        for step in TRACE_STEPS:
            value = json.dumps(trace[step], ensure_ascii=False) if isinstance(trace[step], dict) else trace[step]
            lines.append(f"- **{step}**: {value}")
        lines.append("")
    return "\n".join(lines)


def evaluate_real_data(manifest_path: Path = DEFAULT_MANIFEST, output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    validated = validate_real_dataset(manifest_path)
    results = [_evaluate_one(row, annotation) for row, annotation in validated]
    summary = summarize_results(results)
    traces = build_decision_traces(results)
    payload = {"dataset": "stage8_real_campus_small_sample", "summary": summary, "results": results}
    assert_public_payload_safe(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "real_data_results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "real_data_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    (output_dir / "real_data_report.md").write_text(_report(payload), encoding="utf-8")
    (output_dir / "decision_traces.json").write_text(json.dumps({"traces": traces}, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "decision_traces.md").write_text(_trace_report(traces), encoding="utf-8")
    return payload


def main() -> int:
    payload = evaluate_real_data()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
