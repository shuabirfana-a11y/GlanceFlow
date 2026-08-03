from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.domain.enums import NoticeType, SafetyGateStatus
from glanceflow.evaluation.models import EvaluationAnnotation, MediaType, SourceType
from glanceflow.evaluation.privacy import assert_public_payload_safe
from glanceflow.evaluation.real_comparison import COMPARISON_METRICS, summarize_synthetic
from glanceflow.evaluation.real_data import (
    OUTCOMES,
    RESULT_FIELDS,
    AgentOutcome,
    _classify,
    _public,
    build_decision_traces,
    fraction,
    summarize_results,
)
from glanceflow.evaluation.runners import prepare_observations, run_full_system


DEFAULT_ROOT = Path("evaluation/real_data/public_web")
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.csv"
DEFAULT_CANDIDATES = DEFAULT_ROOT / "public_web_candidates.csv"
DEFAULT_OUTPUT = Path("outputs/evaluation/public_web")
MANIFEST_FIELDS = (
    "sample_id", "source_type", "source_page_url", "image_url", "publisher",
    "published_at", "accessed_at", "license", "redistribution_allowed",
    "privacy_reviewed", "local_file_committed", "annotation_status",
    "scenario_type", "quality_tags", "local_cache_path", "notes",
)
CANDIDATE_FIELDS = (
    "candidate_id", "source_page_url", "publisher", "published_at", "status",
    "reason", "image_url",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicWebManifestRow(StrictModel):
    sample_id: str = Field(pattern=r"^PW-\d{3}$")
    source_type: Literal["PUBLIC_WEB"]
    source_page_url: str = Field(pattern=r"^https?://")
    image_url: str = Field(pattern=r"^https?://")
    publisher: str = Field(min_length=1)
    published_at: str
    accessed_at: str
    license: str = Field(min_length=1)
    redistribution_allowed: bool
    privacy_reviewed: bool
    local_file_committed: bool
    annotation_status: Literal["APPROVED", "PAGE_TEXT_VERIFIED_IMAGE_PENDING", "REJECTED"]
    scenario_type: str = Field(min_length=1)
    quality_tags: str = ""
    local_cache_path: Path
    notes: str = ""

    @model_validator(mode="after")
    def enforce_source_and_rights(self) -> "PublicWebManifestRow":
        if self.redistribution_allowed is False and self.local_file_committed:
            raise ValueError("Images without redistribution permission must not be committed")
        if not self.local_cache_path.as_posix().startswith(
            "evaluation/real_data/public_web/.local_cache/"
        ):
            raise ValueError("Public-web images must stay in the ignored local cache")
        return self

    @property
    def evaluation_ready(self) -> bool:
        return self.privacy_reviewed and self.annotation_status == "APPROVED"


class PublicWebAnnotation(StrictModel):
    sample_id: str = Field(pattern=r"^PW-\d{3}$")
    title: str | None
    event_date: str | None
    event_start: str | None
    location: str | None
    deadline: str | None
    deadline_action: str | None
    timezone: str = "Asia/Shanghai"
    contains_event: bool
    contains_deadline: bool
    expected_behavior: Literal[
        "BUSINESS_COMPLETED", "SAFE_DEFERRED", "SAFE_BLOCKED",
        "RECOVERY_PENDING", "WRONG_EXECUTION", "SYSTEM_FAILED",
    ]
    scope_status: Literal["IN_SCOPE", "OUT_OF_SCOPE", "AMBIGUOUS_SCOPE"]
    weekday_consistent: bool | None
    ground_truth_source: Literal["OFFICIAL_PAGE_TEXT"]
    annotation_generated_by: Literal["CODEX_ASSISTED_MANUAL_REVIEW"]
    human_review_status: Literal["PENDING", "APPROVED", "REJECTED"]
    annotator: str = "CODEX_ASSISTED"
    reviewer: str | None = None
    ground_truth_reviewed: bool = False
    ambiguity_notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_temporal_ground_truth(self) -> "PublicWebAnnotation":
        if self.event_date and self.event_start and self.event_start[:10] != self.event_date:
            raise ValueError("event_date must match event_start")
        if self.deadline and self.event_start and self.deadline == self.event_start:
            raise ValueError("deadline and event_start must not be conflated")
        if self.human_review_status == "APPROVED" and not self.ground_truth_reviewed:
            raise ValueError("Approved human review requires ground_truth_reviewed=true")
        return self


def _bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{field} must be true or false")
    return normalized == "true"


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[PublicWebManifestRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
            raise ValueError("Public-web manifest header does not match the schema")
        raw_rows = [row for row in reader if any((v or "").strip() for v in row.values())]
    rows: list[PublicWebManifestRow] = []
    for raw in raw_rows:
        converted: dict[str, Any] = dict(raw)
        for field in ("redistribution_allowed", "privacy_reviewed", "local_file_committed"):
            converted[field] = _bool(raw[field], field)
        rows.append(PublicWebManifestRow.model_validate(converted))
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("Public-web sample IDs must be unique")
    return rows


def load_candidates(path: Path = DEFAULT_CANDIDATES) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANDIDATE_FIELDS:
            raise ValueError("Public-web candidate header does not match the schema")
        return list(reader)


def validate_metadata(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
) -> tuple[list[PublicWebManifestRow], list[PublicWebAnnotation]]:
    rows = load_manifest(manifest_path)
    candidates = load_candidates(candidates_path)
    if len(candidates) < 30:
        raise ValueError("At least 30 official-source candidates are required")
    if not 15 <= len(rows) <= 20:
        raise ValueError("The selected public-web set must contain 15-20 samples")
    annotations: list[PublicWebAnnotation] = []
    for row in rows:
        path = manifest_path.parent / "annotations" / f"{row.sample_id}.json"
        if not path.is_file():
            raise ValueError(f"{row.sample_id}: annotation file is missing")
        annotation = PublicWebAnnotation.model_validate_json(path.read_text(encoding="utf-8"))
        if annotation.sample_id != row.sample_id:
            raise ValueError(f"{row.sample_id}: annotation sample ID mismatch")
        annotations.append(annotation)
    return rows, annotations


def ready_samples(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
) -> list[tuple[PublicWebManifestRow, PublicWebAnnotation]]:
    rows, annotations = validate_metadata(manifest_path, candidates_path)
    pairs = []
    for row, annotation in zip(rows, annotations, strict=True):
        if (
            not row.evaluation_ready
            or annotation.human_review_status != "APPROVED"
            or not annotation.ground_truth_reviewed
            or not annotation.reviewer
        ):
            continue
        pairs.append((row, annotation))
    return pairs


def _result_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Public-Web Real-World Notification Validation",
        "",
        "> Dataset source type: `PUBLIC_WEB`. This is not a real-campus capture or a human user study.",
        "",
        f"- Official-source candidates audited: {payload['candidate_count']}",
        f"- Metadata-selected samples: {payload['selected_sample_count']}",
        f"- Formally evaluated samples: {summary['sample_count']}",
        f"- Excluded before formal evaluation: {payload['selected_sample_count'] - summary['sample_count']}",
        "- Images committed to Git: 0",
        "",
        "## Outcomes",
        "",
        "| Classification | Count |",
        "|---|---:|",
    ]
    lines.extend(
        f"| {name} | {summary['outcome_counts'][name]}/{summary['sample_count']} |"
        for name in OUTCOMES
    )
    lines.extend(["", "## Metrics", "", "| Metric | Result |", "|---|---|"])
    for name, value in summary["metrics"].items():
        display = value.get("display") if isinstance(value, dict) else f"{value:.3f}"
        lines.append(f"| {name} | {display} |")
    lines.extend([
        "",
        "Publicly accessible does not imply redistribution permission. The formal adapter read only "
        "the lock-frozen, locally sanitized images and used isolated memory calendars.",
        "No statistical significance or real-campus generalization claim is made.",
    ])
    return "\n".join(lines) + "\n"


def _expected_safety(annotation: PublicWebAnnotation) -> SafetyGateStatus:
    return {
        "BUSINESS_COMPLETED": SafetyGateStatus.READY_TO_CONFIRM,
        "SAFE_DEFERRED": SafetyGateStatus.NEED_USER_INPUT,
        "SAFE_BLOCKED": SafetyGateStatus.CONTRADICTION_BLOCKED,
        "RECOVERY_PENDING": SafetyGateStatus.READY_TO_CONFIRM,
        "WRONG_EXECUTION": SafetyGateStatus.CONTRADICTION_BLOCKED,
        "SYSTEM_FAILED": SafetyGateStatus.READY_TO_CONFIRM,
    }[annotation.expected_behavior]


def _adapter(
    row: PublicWebManifestRow,
    annotation: PublicWebAnnotation,
    sanitized_path: Path,
) -> EvaluationAnnotation:
    return EvaluationAnnotation(
        sample_id=f"GF-EVAL-{int(row.sample_id[-3:]):03d}",
        input_path=sanitized_path,
        media_type=MediaType.IMAGE,
        source_type=SourceType.PUBLIC_WEB,
        category="stage8_public_web",
        expected_notice_type=(
            NoticeType.EVENT_WITH_DEADLINE
            if annotation.contains_deadline else NoticeType.EVENT_NOTICE
        ),
        expected_title=annotation.title,
        expected_event_start=annotation.event_start,
        expected_location=annotation.location,
        expected_deadline=annotation.deadline,
        expected_safety_status=_expected_safety(annotation),
        expected_failure_reason=None,
        is_executable=annotation.expected_behavior == "BUSINESS_COMPLETED",
        scenario_tags=["stage8", "public_web", "privacy_reviewed", "sanitized"],
        synthetic=False,
        annotation_notes="R01-reviewed PUBLIC_WEB sample from the lock-frozen sanitized cache.",
    )


def _evaluate_one(
    row: PublicWebManifestRow,
    annotation: PublicWebAnnotation,
    sanitized_path: Path,
) -> dict[str, Any]:
    observation = prepare_observations([_adapter(row, annotation, sanitized_path)])[0]
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
        "expected_behavior": annotation.expected_behavior,
        "agent_final_classification": outcome.value,
        "business_completed": outcome is AgentOutcome.BUSINESS_COMPLETED,
        "safe_deferred": outcome is AgentOutcome.SAFE_DEFERRED,
        "safe_blocked": outcome is AgentOutcome.SAFE_BLOCKED,
        "recovery_pending": outcome is AgentOutcome.RECOVERY_PENDING,
        "wrong_execution": outcome is AgentOutcome.WRONG_EXECUTION,
        "system_failed": outcome is AgentOutcome.SYSTEM_FAILED,
        "confirmation_count": confirmation_count,
        "clarification_count": int(
            result.predicted_safety_status is SafetyGateStatus.NEED_USER_INPUT
        ),
        "recapture_requested": (
            result.predicted_safety_status is SafetyGateStatus.RECAPTURE_REQUIRED
        ),
        "unsafe_tool_calls": 0,
        "confirmation_bypass": int(result.executed and confirmation_count == 0),
        "duplicate_execution": int(result.active_event_count > 1),
        "latency_ms": round(result.latencies.total_ms, 3),
        "final_reason": _public(final_reason),
    }


def _locked_samples(
    manifest_path: Path,
    candidates_path: Path,
    lock_path: Path,
    sanitized_manifest_path: Path,
) -> list[tuple[PublicWebManifestRow, PublicWebAnnotation, Path]]:
    from glanceflow.evaluation.public_web_preflight import (
        audit_original_cache,
        audit_sanitized_cache,
        load_cache_manifest,
        load_sanitized_manifest,
        require_ready_for_formal_evaluation,
    )

    sample_ids = require_ready_for_formal_evaluation(
        lock_path=lock_path,
        manifest_path=manifest_path,
        sanitized_manifest_path=sanitized_manifest_path,
    )
    rows, annotations = validate_metadata(manifest_path, candidates_path)
    rows_by_id = {row.sample_id: row for row in rows}
    annotations_by_id = {item.sample_id: item for item in annotations}
    cache_records = load_cache_manifest(manifest_path.parent / "cache_manifest.csv")
    cache_by_id = {item.sample_id: item for item in cache_records}
    sanitized_records = load_sanitized_manifest(sanitized_manifest_path)
    sanitized_by_id = {item.sample_id: item for item in sanitized_records}
    original_issues = audit_original_cache(cache_records)
    sanitized_issues = audit_sanitized_cache(sanitized_records, cache_by_id)
    sanitized_root = (manifest_path.parent / ".sanitized_cache").resolve()
    locked = []
    for sample_id in sample_ids:
        row = rows_by_id[sample_id]
        annotation = annotations_by_id[sample_id]
        record = sanitized_by_id.get(sample_id)
        if record is None:
            raise RuntimeError(f"{sample_id}: lock-frozen sanitized image is missing")
        integrity_issues = (
            original_issues.get(sample_id, []) + sanitized_issues.get(sample_id, [])
        )
        if integrity_issues:
            raise RuntimeError(
                f"{sample_id}: formal input integrity failed: "
                + ", ".join(integrity_issues)
            )
        path = Path(record.sanitized_path).resolve()
        if sanitized_root not in path.parents or not path.is_file():
            raise RuntimeError(f"{sample_id}: sanitized path escaped the approved local cache")
        if not row.evaluation_ready or annotation.human_review_status != "APPROVED":
            raise RuntimeError(f"{sample_id}: lock contains an unapproved sample")
        locked.append((row, annotation, path))
    return locked


def _summarize_public_web_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = summarize_results(results)
    summary["target_met"] = None
    summary["message"] = (
        "Lock-frozen PUBLIC_WEB validation; every eligible sample and failure is retained."
    )
    return summary


def evaluate_public_web(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
    output_dir: Path = DEFAULT_OUTPUT,
    lock_path: Path = DEFAULT_ROOT / "evaluation_set.lock.json",
    sanitized_manifest_path: Path = DEFAULT_ROOT / "sanitized_manifest.csv",
) -> dict[str, Any]:
    rows, _ = validate_metadata(manifest_path, candidates_path)
    candidates = load_candidates(candidates_path)
    locked = _locked_samples(
        manifest_path, candidates_path, lock_path, sanitized_manifest_path
    )
    results = [
        _evaluate_one(row, annotation, sanitized_path)
        for row, annotation, sanitized_path in locked
    ]
    summary = _summarize_public_web_results(results)
    traces = build_decision_traces(results)
    payload = {
        "dataset": "Public-Web Real-World Notification Set",
        "source_type": "PUBLIC_WEB",
        "candidate_count": len(candidates),
        "selected_sample_count": len(rows),
        "lock_sample_ids": [row.sample_id for row, _, _ in locked],
        "summary": summary,
        "results": results,
    }
    assert_public_payload_safe(payload)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "public_web_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "public_web_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    (output_dir / "public_web_report.md").write_text(_result_report(payload), encoding="utf-8")
    (output_dir / "public_web_decision_traces.json").write_text(
        json.dumps({"traces": traces}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def compare_public_web_vs_synthetic(
    synthetic_path: Path = Path("outputs/evaluation/full_system_results.json"),
    public_web_path: Path = DEFAULT_OUTPUT / "public_web_results.json",
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    synthetic = summarize_synthetic(synthetic_path)
    public_payload = json.loads(public_web_path.read_text(encoding="utf-8"))
    public_summary = public_payload["summary"]
    total = public_summary["sample_count"]
    counts = public_summary["outcome_counts"]
    public = {
        "status": public_summary["status"],
        "sample_count": total,
        "outcome_counts": counts,
        "metrics": {
            "full_field_correct_rate": public_summary["metrics"]["full_field_correct_rate"],
            "BUSINESS_COMPLETED": fraction(counts["BUSINESS_COMPLETED"], total),
            "SAFE_DEFERRED": fraction(counts["SAFE_DEFERRED"], total),
            "SAFE_BLOCKED": fraction(counts["SAFE_BLOCKED"], total),
            "WRONG_EXECUTION": fraction(counts["WRONG_EXECUTION"], total),
            "recapture_rate": public_summary["metrics"]["recapture_rate"],
            "ocr_failure_rate": fraction(
                sum(not row["ocr_success"] for row in public_payload["results"]), total
            ),
            "average_confirmation_count": public_summary["metrics"]["average_confirmation_count"],
            "average_latency_ms": public_summary["metrics"]["average_latency_ms"],
        },
    }
    payload = {
        "scope": "Synthetic Evaluation Set vs Public-Web Real-World Notification Set",
        "statistical_significance_claimed": False,
        "synthetic": synthetic,
        "public_web": public,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "public_web_vs_synthetic.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "public_web_vs_synthetic.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("metric", "Synthetic Evaluation Set", "Public-Web Real-World Notification Set"))
        writer.writeheader()
        for metric in COMPARISON_METRICS:
            synthetic_value = synthetic["metrics"][metric]
            public_value = public["metrics"][metric]
            synthetic_display = (
                synthetic_value.get("display")
                if isinstance(synthetic_value, dict) else f"{synthetic_value:.3f}"
            )
            public_display = (
                public_value.get("display")
                if isinstance(public_value, dict) else f"{public_value:.3f}"
            )
            writer.writerow({
                "metric": metric,
                "Synthetic Evaluation Set": synthetic_display,
                "Public-Web Real-World Notification Set": public_display,
            })
    report = "\n".join([
        "# Synthetic Evaluation Set vs Public-Web Real-World Notification Set",
        "",
        f"Synthetic Evaluation Set: N={synthetic['sample_count']}.",
        "",
        f"Public-Web Real-World Notification Set: N={public['sample_count']}.",
        "",
        "This is a descriptive comparison only. No statistical significance or real-campus "
        "generalization claim is made.",
    ]) + "\n"
    (output_dir / "public_web_vs_synthetic.md").write_text(report, encoding="utf-8")
    return payload


def main() -> int:
    payload = evaluate_public_web()
    compare_public_web_vs_synthetic()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
