from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import CreateEventRequest, EventRole, TransactionStatus, UserConfirmation
from glanceflow.calendar.rollback import rollback_events
from glanceflow.calendar.transaction import plan_event_requests
from glanceflow.calendar.verification import verify_readback
from glanceflow.domain.enums import DeadlineRole, NoticeType, SafetyGateStatus
from glanceflow.domain.models import DeadlineAction, FieldEvidence, MainEvent, NoticePackageDraft
from glanceflow.evaluation.models import EvaluationAnnotation, MediaType, StageLatencies, SystemResult
from glanceflow.extraction.extractor import DeterministicDraftExtractor
from glanceflow.extraction.normalization import normalize_text, parse_datetime_text, strip_label
from glanceflow.extraction.schemas import ExtractionResult
from glanceflow.ocr.models import ImageQualityResult, OcrResult
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.ocr.quality import add_ocr_text_check, inspect_image_quality
from glanceflow.safety.gate import evaluate_notice
from glanceflow.safety.rules import ALL_RULES
from glanceflow.wearable.capture import FileVideoCaptureProvider
from glanceflow.wearable.frame_selection import DeterministicFrameSelector
from glanceflow.wearable.models import CaptureRequest, CaptureResult, FrameSelectionResult


CAPTURED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@dataclass
class Observation:
    annotation: EvaluationAnnotation
    image_path: Path
    quality: ImageQualityResult
    ocr: OcrResult
    frame_capture_ms: float
    frame_selection_ms: float
    selection_eligible: bool
    capture_result: CaptureResult | None = None
    selection_result: FrameSelectionResult | None = None


@dataclass(frozen=True)
class AblationConfig:
    ablation_id: str
    quality_gate: bool = True
    disabled_safety_rules: frozenset[str] = frozenset()
    duplicate_detection: bool = True
    conflict_preflight: bool = True
    readback_verification: bool = True
    atomic_rollback: bool = True


ABLATIONS = (
    AblationConfig("no_image_quality_gate", quality_gate=False),
    AblationConfig("no_evidence_confidence_rule", disabled_safety_rules=frozenset({"GF-CONFIDENCE-001"})),
    AblationConfig("no_weekday_consistency", disabled_safety_rules=frozenset({"GF-TIME-004"})),
    AblationConfig("no_duplicate_detection", disabled_safety_rules=frozenset({"GF-DUPLICATE-001"}), duplicate_detection=False),
    AblationConfig("no_conflict_preflight", conflict_preflight=False),
    AblationConfig("no_readback_verification", readback_verification=False),
    AblationConfig("no_atomic_rollback", atomic_rollback=False),
)


def prepare_observations(samples: list[EvaluationAnnotation]) -> list[Observation]:
    provider = RapidOcrProvider()
    selector = DeterministicFrameSelector(provider=provider)
    capture_provider = FileVideoCaptureProvider()
    observations: list[Observation] = []
    for sample in samples:
        capture_ms = 0.0
        selection_ms = 0.0
        capture_result = None
        selection_result = None
        path = Path(sample.input_path)
        selection_eligible = True
        if sample.media_type is MediaType.VIDEO:
            started = perf_counter()
            capture_result = capture_provider.capture(CaptureRequest(
                session_id=f"eval-{sample.sample_id}", video_path=path,
                output_dir=Path("work/evaluation-frames"), delete_source_after_processing=False,
            ))
            capture_ms = (perf_counter() - started) * 1000
            started = perf_counter()
            selection_result = selector.select(capture_result)
            selection_ms = (perf_counter() - started) * 1000
            selection_eligible = not selection_result.requires_recapture
            if selection_result.selected_image_path:
                path = selection_result.selected_image_path
            else:
                best = max(selection_result.scores, key=lambda score: score.total_score)
                path = next(frame.image_path for frame in capture_result.sampled_frames if frame.frame_id == best.frame_id)
        quality = inspect_image_quality(path)
        ocr = provider.recognize(path, sample.sample_id)
        quality = add_ocr_text_check(quality, [line.text for line in ocr.evidence_lines]) if ocr.success else quality
        observations.append(Observation(sample, path, quality, ocr, capture_ms, selection_ms, selection_eligible, capture_result, selection_result))
    return observations


def _fault_plan(sample: EvaluationAnnotation) -> MemoryFaultPlan:
    if sample.fault_plan == "READBACK_MISMATCH":
        return MemoryFaultPlan(tamper_readback_by_role={"MAIN_EVENT": {"title": "供应商回读异常标题"}})
    if sample.fault_plan == "SECOND_CREATE_FAILURE":
        return MemoryFaultPlan(fail_create_on_calls={2})
    return MemoryFaultPlan()


def _seed_context(provider: MemoryCalendarProvider, draft: NoticePackageDraft, sample: EvaluationAnnotation) -> tuple[list[NoticePackageDraft], set[str]]:
    existing: list[NoticePackageDraft] = []
    seed_ids: set[str] = set()
    if sample.existing_context == "DUPLICATE":
        existing.append(draft.model_copy(update={"notice_package_id": "GF-PKG-9999"}, deep=True))
        request = plan_event_requests(existing[0], "GF-EVAL-SEED-DUPLICATE")[0]
        seed_ids.add(provider.create_event(request, f"seed-{sample.sample_id}").event_id)
    elif sample.existing_context == "CONFLICT":
        start = draft.main_event.event_start + timedelta(minutes=30)
        request = CreateEventRequest(
            title="已有课程", start_time=start, end_time=start + timedelta(hours=1),
            timezone=draft.timezone, location="教学楼101", description="评测预置冲突事件。",
            private_metadata={"notice_package_id":"seed-conflict","transaction_id":"seed-conflict","event_role":"MAIN_EVENT"},
            notice_package_id="seed-conflict", transaction_id="seed-conflict", event_role=EventRole.MAIN_EVENT,
        )
        seed_ids.add(provider.create_event(request, f"seed-{sample.sample_id}").event_id)
    return existing, seed_ids


def _extract(observation: Observation) -> tuple[ExtractionResult, float]:
    started = perf_counter()
    result = DeterministicDraftExtractor().extract(observation.ocr, CAPTURED_AT, "Asia/Shanghai")
    return result, (perf_counter() - started) * 1000


def _draft_fields(draft: NoticePackageDraft | None) -> dict:
    if draft is None:
        return {}
    return {
        "title": draft.main_event.title or None,
        "event_start": draft.main_event.event_start.isoformat(),
        "location": draft.main_event.location or None,
        "deadline": draft.deadline_action.deadline.isoformat() if draft.deadline_action else None,
    }


def _fields_match(sample: EvaluationAnnotation, fields: dict) -> bool:
    return all((
        fields.get("title") == sample.expected_title,
        fields.get("event_start") == sample.expected_event_start,
        fields.get("location") == sample.expected_location,
        fields.get("deadline") == sample.expected_deadline,
    ))


def _finalize(
    observation: Observation,
    system_id: str,
    predicted_status: SafetyGateStatus,
    *,
    fields: dict,
    extracted_fields: dict | None,
    active_event_count: int,
    readback_verified: bool | None = None,
    rollback_attempted: bool = False,
    rollback_succeeded: bool | None = None,
    duplicate_detected: bool | None = None,
    conflict_detected: bool | None = None,
    transaction_status: str | None = None,
    failure_layer: str | None = None,
    failure_reasons: list[str] | None = None,
    extraction_ms: float = 0,
    safety_ms: float = 0,
    calendar_ms: float = 0,
) -> SystemResult:
    sample = observation.annotation
    executed = active_event_count > 0
    matches = _fields_match(sample, fields)
    correct_execution = bool(sample.is_executable and executed and matches)
    erroneous = bool(executed and not correct_execution)
    false_rejection = bool(sample.is_executable and not correct_execution)
    total = observation.frame_capture_ms + observation.frame_selection_ms + observation.ocr.processing_time_ms + extraction_ms + safety_ms + calendar_ms
    return SystemResult(
        sample_id=sample.sample_id, system_id=system_id, predicted_safety_status=predicted_status,
        executed=executed, active_event_count=active_event_count,
        actual_title=fields.get("title"), actual_event_start=fields.get("event_start"),
        actual_location=fields.get("location"), actual_deadline=fields.get("deadline"),
        fields_match=matches, correct_execution=correct_execution, erroneous_execution=erroneous,
        false_rejection=false_rejection, package_completely_correct=correct_execution,
        readback_verified=readback_verified, rollback_attempted=rollback_attempted,
        rollback_succeeded=rollback_succeeded, duplicate_detected=duplicate_detected,
        conflict_detected=conflict_detected, transaction_status=transaction_status,
        failure_layer=failure_layer, failure_reasons=failure_reasons or [],
        ocr_lines=[{"text": line.text, "confidence": line.confidence} for line in observation.ocr.evidence_lines],
        extracted_fields=extracted_fields,
        latencies=StageLatencies(
            frame_capture_ms=observation.frame_capture_ms, frame_selection_ms=observation.frame_selection_ms,
            ocr_ms=observation.ocr.processing_time_ms, extraction_ms=extraction_ms,
            safety_gate_ms=safety_ms, calendar_transaction_ms=calendar_ms, total_ms=total,
        ),
    )


def _confirmation(service: TrustedSchedulingService, tx_id: str) -> UserConfirmation:
    record = service.get_transaction(tx_id)
    main = next(request for request in record.planned_requests if request.event_role is EventRole.MAIN_EVENT)
    deadline = next((request for request in record.planned_requests if request.event_role is EventRole.DEADLINE_EVENT), None)
    return UserConfirmation(
        confirmed=True, confirmed_at=CAPTURED_AT, confirmed_title=main.title,
        confirmed_event_start=main.start_time, confirmed_location=main.location,
        confirmed_deadline=deadline.start_time if deadline else None,
        accepted_conflict=False, confirmation_source="stage5-evaluation-protocol",
    )


def run_full_system(observation: Observation) -> SystemResult:
    extraction, extraction_ms = _extract(observation)
    extracted = _draft_fields(extraction.draft)
    quality_blocked = not observation.quality.passed or not observation.selection_eligible
    if quality_blocked:
        return _finalize(observation, "full_system", SafetyGateStatus.RECAPTURE_REQUIRED, fields={}, extracted_fields=extracted or None, active_event_count=0, failure_layer="quality_or_frame_selection", failure_reasons=observation.quality.rejection_reasons or ["没有合格视频帧。"], extraction_ms=extraction_ms)
    if not extraction.success or extraction.draft is None:
        status = extraction.suggested_status or SafetyGateStatus.NEED_USER_INPUT
        reasons = [issue.message for issue in extraction.issues] + extraction.ambiguity_reasons
        return _finalize(observation, "full_system", status, fields={}, extracted_fields=None, active_event_count=0, failure_layer="extraction", failure_reasons=list(dict.fromkeys(reasons)), extraction_ms=extraction_ms)
    provider = MemoryCalendarProvider(_fault_plan(observation.annotation))
    existing, seed_ids = _seed_context(provider, extraction.draft, observation.annotation)
    started = perf_counter()
    decision = evaluate_notice(extraction.draft, existing)
    safety_ms = (perf_counter() - started) * 1000
    if not decision.can_proceed_to_confirmation:
        reasons = decision.blocking_reasons + decision.required_user_inputs + decision.recapture_reasons
        return _finalize(observation, "full_system", decision.status, fields={}, extracted_fields=extracted, active_event_count=0, duplicate_detected=observation.annotation.existing_context == "DUPLICATE", failure_layer="safety_gate", failure_reasons=reasons, extraction_ms=extraction_ms, safety_ms=safety_ms)
    service = TrustedSchedulingService(provider)
    started = perf_counter()
    preflight = service.preflight(extraction.draft, decision, transaction_id=f"GF-TX-EVAL-{observation.annotation.sample_id}")
    if not preflight.passed or preflight.requires_conflict_confirmation:
        calendar_ms = (perf_counter() - started) * 1000
        return _finalize(observation, "full_system", decision.status, fields={}, extracted_fields=extracted, active_event_count=0, duplicate_detected=preflight.duplicate_result.is_duplicate, conflict_detected=preflight.conflict_result.has_conflict, transaction_status="WAITING_CONFIRMATION" if preflight.passed else "CANCELLED", failure_layer="preflight", failure_reasons=preflight.messages, extraction_ms=extraction_ms, safety_ms=safety_ms, calendar_ms=calendar_ms)
    service.confirm(preflight.transaction_id, _confirmation(service, preflight.transaction_id))
    transaction = service.execute(preflight.transaction_id)
    calendar_ms = (perf_counter() - started) * 1000
    active_ids = set(provider.event_ids) - seed_ids
    fields = _draft_fields(extraction.draft) if transaction.status is TransactionStatus.VERIFIED else {}
    verified = all(result.passed for result in transaction.verification_results) if transaction.verification_results else None
    rollback_attempted = bool(transaction.rollback_results)
    rollback_succeeded = all(item.delete_succeeded and item.absence_verified for item in transaction.rollback_results) if rollback_attempted else None
    return _finalize(observation, "full_system", decision.status, fields=fields, extracted_fields=extracted, active_event_count=len(active_ids), readback_verified=verified, rollback_attempted=rollback_attempted, rollback_succeeded=rollback_succeeded, duplicate_detected=preflight.duplicate_result.is_duplicate, conflict_detected=preflight.conflict_result.has_conflict, transaction_status=transaction.status.value, failure_layer=None if transaction.status is TransactionStatus.VERIFIED else "calendar_transaction", failure_reasons=[] if transaction.status is TransactionStatus.VERIFIED else ["事务未通过回读或创建，已按策略回滚。"], extraction_ms=extraction_ms, safety_ms=safety_ms, calendar_ms=calendar_ms)


def _regex_extract(observation: Observation) -> tuple[NoticePackageDraft | None, float, list[str]]:
    started = perf_counter()
    title_line = next((line for line in observation.ocr.evidence_lines if re.search(r"活动标题\s*[:：]", line.text)), None)
    location_line = next((line for line in observation.ocr.evidence_lines if re.search(r"(?:活动)?地点\s*[:：]", line.text)), None)
    deadline_line = next((line for line in observation.ocr.evidence_lines if "截止" in normalize_text(line.text) and parse_datetime_text(line.text, "Asia/Shanghai")), None)
    event_lines = [line for line in observation.ocr.evidence_lines if line is not deadline_line and parse_datetime_text(line.text, "Asia/Shanghai")]
    title = strip_label(title_line.text, ("活动标题", "标题")) if title_line else ""
    location = strip_label(location_line.text, ("活动地点", "地点")) if location_line else ""
    if not title or not location or not event_lines:
        return None, (perf_counter() - started) * 1000, ["简单正则未找到完整标题、时间和地点。"]
    event_line = event_lines[0]
    event_start, raw_date, raw_weekday = parse_datetime_text(event_line.text, "Asia/Shanghai")
    deadline_action = None
    if deadline_line:
        deadline, _, _ = parse_datetime_text(deadline_line.text, "Asia/Shanghai")
        action_line = next((line for line in observation.ocr.evidence_lines if "截止动作" in normalize_text(line.text)), None)
        action = strip_label(action_line.text, ("截止动作",)) if action_line else "提交事项"
        deadline_action = DeadlineAction(deadline=deadline, action=action, role=DeadlineRole.REGISTRATION, deadline_evidence=FieldEvidence(evidence_line_ids=[deadline_line.line_id], confidence=deadline_line.confidence), action_evidence=FieldEvidence(evidence_line_ids=[action_line.line_id] if action_line else [], confidence=action_line.confidence if action_line else 1.0))
    draft = NoticePackageDraft(
        notice_package_id=f"GF-PKG-{int(observation.annotation.sample_id[-3:]):04d}",
        notice_type=NoticeType.EVENT_WITH_DEADLINE if deadline_action else NoticeType.EVENT_NOTICE,
        captured_at=CAPTURED_AT, timezone="Asia/Shanghai", source_frame_id=observation.ocr.source_frame_id,
        main_event=MainEvent(title=title, event_start=event_start, location=location,
            title_evidence=FieldEvidence(evidence_line_ids=[title_line.line_id], confidence=title_line.confidence),
            time_evidence=FieldEvidence(evidence_line_ids=[event_line.line_id], confidence=event_line.confidence),
            location_evidence=FieldEvidence(evidence_line_ids=[location_line.line_id], confidence=location_line.confidence),
            raw_date_text=raw_date, raw_weekday_text=raw_weekday),
        deadline_action=deadline_action, evidence_lines=observation.ocr.evidence_lines,
        extraction_version="evaluation-simple-regex-v1", metadata={"baseline":"A"},
    )
    return draft, (perf_counter() - started) * 1000, []


def _direct_write(provider: MemoryCalendarProvider, draft: NoticePackageDraft, tx_id: str, *, verify: bool, atomic_rollback: bool) -> tuple[list[str], dict, bool | None, bool, bool | None, str, list[str]]:
    requests = plan_event_requests(draft, tx_id)
    created: list[str] = []
    verified: bool | None = None
    rollback_attempted = False
    rollback_succeeded: bool | None = None
    status = "CREATING"
    reasons: list[str] = []
    try:
        for request in requests:
            snapshot = provider.create_event(request, f"{tx_id}:{request.event_role.value}")
            created.append(snapshot.event_id)
    except Exception as exc:
        reasons.append(f"创建失败：{type(exc).__name__}")
        if atomic_rollback and created:
            rollback_attempted = True
            results = rollback_events(provider, created)
            rollback_succeeded = all(item.delete_succeeded and item.absence_verified for item in results)
            status = "ROLLED_BACK" if rollback_succeeded else "FAILED"
        else:
            status = "PARTIAL_WRITE"
    else:
        if verify:
            checks = []
            for request, event_id in zip(requests, created, strict=True):
                checks.append(verify_readback(request, provider.get_event(event_id)))
            verified = all(check.passed for check in checks)
            if not verified:
                reasons.append("回读字段不一致。")
                if atomic_rollback:
                    rollback_attempted = True
                    results = rollback_events(provider, created)
                    rollback_succeeded = all(item.delete_succeeded and item.absence_verified for item in results)
                    status = "ROLLED_BACK" if rollback_succeeded else "FAILED"
                else:
                    status = "READBACK_MISMATCH_LEFT_ACTIVE"
            else:
                status = "VERIFIED"
        else:
            status = "CREATED_WITHOUT_READBACK"
    active = [event_id for event_id in created if event_id in provider.event_ids]
    fields = _draft_fields(draft) if active else {}
    if active and len(active) < len(requests):
        fields["deadline"] = None
    if active:
        # Evaluation observer inspects the isolated memory provider after the
        # system returns. This is measurement, not baseline readback logic.
        try:
            actual_main = provider.get_event(active[0])
            fields.update(title=actual_main.title, event_start=actual_main.start_time.isoformat(), location=actual_main.location)
        except Exception:
            pass
    return active, fields, verified, rollback_attempted, rollback_succeeded, status, reasons


def run_baseline_a(observation: Observation) -> SystemResult:
    draft, extraction_ms, reasons = _regex_extract(observation)
    if draft is None:
        return _finalize(observation, "baseline_a_regex_direct", SafetyGateStatus.NEED_USER_INPUT, fields={}, extracted_fields=None, active_event_count=0, failure_layer="regex_extraction", failure_reasons=reasons, extraction_ms=extraction_ms)
    provider = MemoryCalendarProvider(_fault_plan(observation.annotation))
    _, seed_ids = _seed_context(provider, draft, observation.annotation)
    started = perf_counter()
    active, fields, verified, rollback_attempted, rollback_succeeded, status, write_reasons = _direct_write(provider, draft, f"GF-TX-A-{observation.annotation.sample_id}", verify=False, atomic_rollback=False)
    calendar_ms = (perf_counter() - started) * 1000
    return _finalize(observation, "baseline_a_regex_direct", SafetyGateStatus.READY_TO_CONFIRM, fields=fields, extracted_fields=_draft_fields(draft), active_event_count=len(active), readback_verified=verified, rollback_attempted=rollback_attempted, rollback_succeeded=rollback_succeeded, transaction_status=status, failure_layer=None if not write_reasons else "calendar_write", failure_reasons=write_reasons, extraction_ms=extraction_ms, calendar_ms=calendar_ms)


def run_baseline_b(observation: Observation) -> SystemResult:
    extraction, extraction_ms = _extract(observation)
    if not extraction.success or extraction.draft is None:
        status = extraction.suggested_status or SafetyGateStatus.NEED_USER_INPUT
        return _finalize(observation, "baseline_b_extractor_no_safety", status, fields={}, extracted_fields=None, active_event_count=0, failure_layer="extraction", failure_reasons=[issue.message for issue in extraction.issues], extraction_ms=extraction_ms)
    draft = extraction.draft
    if not all((draft.main_event.title.strip(), draft.main_event.location.strip())):
        return _finalize(observation, "baseline_b_extractor_no_safety", SafetyGateStatus.NEED_USER_INPUT, fields={}, extracted_fields=_draft_fields(draft), active_event_count=0, failure_layer="confirmation", failure_reasons=["确认界面字段不完整。"], extraction_ms=extraction_ms)
    provider = MemoryCalendarProvider(_fault_plan(observation.annotation))
    _seed_context(provider, draft, observation.annotation)
    started = perf_counter()
    active, fields, verified, rollback_attempted, rollback_succeeded, status, reasons = _direct_write(provider, draft, f"GF-TX-B-{observation.annotation.sample_id}", verify=False, atomic_rollback=False)
    calendar_ms = (perf_counter() - started) * 1000
    return _finalize(observation, "baseline_b_extractor_no_safety", SafetyGateStatus.READY_TO_CONFIRM, fields=fields, extracted_fields=_draft_fields(draft), active_event_count=len(active), readback_verified=verified, rollback_attempted=rollback_attempted, rollback_succeeded=rollback_succeeded, transaction_status=status, failure_layer=None if not reasons else "calendar_write", failure_reasons=reasons, extraction_ms=extraction_ms, calendar_ms=calendar_ms)


_BLOCKING = {"GF-TIME-001","GF-TIME-002","GF-TIME-003","GF-TIME-004","GF-DEADLINE-002","GF-NOTICE-001","GF-DUPLICATE-001"}
_RECAPTURE = {"GF-EVIDENCE-002","GF-EVIDENCE-003","GF-CONFIDENCE-001"}
_INPUT = {"GF-FIELD-001","GF-FIELD-002","GF-TIME-005","GF-DEADLINE-001","GF-EVIDENCE-001"}
_RULE_NAMES = {
    "GF-CONFIDENCE-001": "rule_confidence_001",
    "GF-TIME-004": "rule_time_004",
    "GF-DUPLICATE-001": "rule_duplicate_001",
}


def _ablated_safety(draft: NoticePackageDraft, existing: list[NoticePackageDraft], config: AblationConfig) -> tuple[SafetyGateStatus, list[str]]:
    disabled_names = {_RULE_NAMES[rule_id] for rule_id in config.disabled_safety_rules}
    failures = []
    for rule in ALL_RULES:
        if rule.__name__ in disabled_names:
            continue
        result = rule(draft, existing)
        if not result.passed:
            failures.append(result)
    ids = {result.rule_id for result in failures}
    if ids & _BLOCKING:
        status = SafetyGateStatus.CONTRADICTION_BLOCKED
    elif ids & _RECAPTURE:
        status = SafetyGateStatus.RECAPTURE_REQUIRED
    elif ids & _INPUT:
        status = SafetyGateStatus.NEED_USER_INPUT
    else:
        status = SafetyGateStatus.READY_TO_CONFIRM
    return status, [result.message for result in failures]


def run_ablation(observation: Observation, config: AblationConfig) -> SystemResult:
    extraction, extraction_ms = _extract(observation)
    quality_blocked = (not observation.quality.passed or not observation.selection_eligible) and config.quality_gate
    if quality_blocked:
        return _finalize(observation, config.ablation_id, SafetyGateStatus.RECAPTURE_REQUIRED, fields={}, extracted_fields=_draft_fields(extraction.draft) or None, active_event_count=0, failure_layer="quality_or_frame_selection", failure_reasons=observation.quality.rejection_reasons or ["没有合格视频帧。"], extraction_ms=extraction_ms)
    if not extraction.success or extraction.draft is None:
        status = extraction.suggested_status or SafetyGateStatus.NEED_USER_INPUT
        return _finalize(observation, config.ablation_id, status, fields={}, extracted_fields=None, active_event_count=0, failure_layer="extraction", failure_reasons=[issue.message for issue in extraction.issues] + extraction.ambiguity_reasons, extraction_ms=extraction_ms)
    draft = extraction.draft
    provider = MemoryCalendarProvider(_fault_plan(observation.annotation))
    existing, seed_ids = _seed_context(provider, draft, observation.annotation)
    started = perf_counter()
    status, reasons = _ablated_safety(draft, existing, config)
    safety_ms = (perf_counter() - started) * 1000
    if status is not SafetyGateStatus.READY_TO_CONFIRM:
        return _finalize(observation, config.ablation_id, status, fields={}, extracted_fields=_draft_fields(draft), active_event_count=0, duplicate_detected=observation.annotation.existing_context == "DUPLICATE" and config.duplicate_detection, failure_layer="safety_gate", failure_reasons=reasons, extraction_ms=extraction_ms, safety_ms=safety_ms)
    duplicate = observation.annotation.existing_context == "DUPLICATE" and config.duplicate_detection
    conflict = observation.annotation.existing_context == "CONFLICT" and config.conflict_preflight
    if duplicate or conflict:
        return _finalize(observation, config.ablation_id, status, fields={}, extracted_fields=_draft_fields(draft), active_event_count=0, duplicate_detected=duplicate, conflict_detected=conflict, transaction_status="WAITING_CONFIRMATION" if conflict else "CANCELLED", failure_layer="preflight", failure_reasons=["重复或冲突预检阻止当前评测协议执行。"], extraction_ms=extraction_ms, safety_ms=safety_ms)
    started = perf_counter()
    active, fields, verified, rollback_attempted, rollback_succeeded, tx_status, write_reasons = _direct_write(provider, draft, f"GF-TX-ABL-{config.ablation_id}-{observation.annotation.sample_id}", verify=config.readback_verification, atomic_rollback=config.atomic_rollback)
    calendar_ms = (perf_counter() - started) * 1000
    active = [event_id for event_id in active if event_id not in seed_ids]
    return _finalize(observation, config.ablation_id, status, fields=fields, extracted_fields=_draft_fields(draft), active_event_count=len(active), readback_verified=verified, rollback_attempted=rollback_attempted, rollback_succeeded=rollback_succeeded, duplicate_detected=False if observation.annotation.existing_context == "DUPLICATE" else None, conflict_detected=False if observation.annotation.existing_context == "CONFLICT" else None, transaction_status=tx_status, failure_layer=None if not write_reasons else "calendar_transaction", failure_reasons=write_reasons, extraction_ms=extraction_ms, safety_ms=safety_ms, calendar_ms=calendar_ms)
