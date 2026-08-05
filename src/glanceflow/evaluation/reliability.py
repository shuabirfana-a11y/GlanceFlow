from __future__ import annotations

from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import EventRole, UserConfirmation, calendar_request_digest
from glanceflow.calendar.port import CalendarTransientError
from glanceflow.evaluation.metrics import ratio
from glanceflow.evaluation.runners import CAPTURED_AT, Observation, _extract
from glanceflow.safety.gate import evaluate_notice


def _trial_result(numerator: int, denominator: int) -> dict:
    result = ratio(numerator, denominator).model_dump(mode="json")
    result["display"] = f"{numerator}/{denominator} trials" if denominator else "N/A"
    return result


def _confirmation(service: TrustedSchedulingService, tx_id: str) -> UserConfirmation:
    record = service.get_transaction(tx_id)
    main = next(request for request in record.planned_requests if request.event_role is EventRole.MAIN_EVENT)
    deadline = next((request for request in record.planned_requests if request.event_role is EventRole.DEADLINE_EVENT), None)
    return UserConfirmation(
        confirmed=True, confirmed_at=CAPTURED_AT, confirmed_title=main.title,
        confirmed_event_start=main.start_time, confirmed_location=main.location,
        confirmed_deadline=deadline.start_time if deadline else None,
        confirmed_calendar_id=record.calendar_id,
        confirmed_request_hash=calendar_request_digest(record.planned_requests),
        confirmation_source="stage5-reliability-test",
    )


def run_reliability_trials(full_results: list, observations: list[Observation]) -> dict:
    ready_observation = next(item for item in observations if item.annotation.category == "normal_executable")
    extraction, _ = _extract(ready_observation)
    draft = extraction.draft
    decision = evaluate_notice(draft)

    undo_provider = MemoryCalendarProvider()
    undo_service = TrustedSchedulingService(undo_provider)
    undo_preflight = undo_service.preflight(draft, decision, transaction_id="GF-TX-EVAL-UNDO")
    undo_service.confirm(undo_preflight.transaction_id, _confirmation(undo_service, undo_preflight.transaction_id))
    undo_service.execute(undo_preflight.transaction_id)
    undone = undo_service.undo(undo_preflight.transaction_id)
    undo_ok = undone.status.value == "UNDONE" and undo_provider.event_count == 0

    idem_provider = MemoryCalendarProvider(MemoryFaultPlan(timeout_after_create_on_calls={1}))
    idem_service = TrustedSchedulingService(idem_provider)
    idem_preflight = idem_service.preflight(draft, decision, transaction_id="GF-TX-EVAL-IDEMPOTENCY")
    idem_service.confirm(idem_preflight.transaction_id, _confirmation(idem_service, idem_preflight.transaction_id))
    first_timed_out = False
    try:
        idem_service.execute(idem_preflight.transaction_id)
    except CalendarTransientError:
        first_timed_out = True
    retried = idem_service.execute(idem_preflight.transaction_id)
    idem_ok = first_timed_out and retried.status.value == "VERIFIED" and idem_provider.event_count == 1

    readbacks = [result for result in full_results if result.readback_verified is not None]
    rollbacks = [result for result in full_results if result.rollback_attempted]
    duplicates = [result for result in full_results if result.duplicate_detected is not None and result.sample_id in {item.annotation.sample_id for item in observations if item.annotation.existing_context == "DUPLICATE"}]
    conflicts = [result for result in full_results if result.conflict_detected is not None and result.sample_id in {item.annotation.sample_id for item in observations if item.annotation.existing_context == "CONFLICT"}]
    return {
        "readback_consistency_rate": _trial_result(sum(result.readback_verified is True for result in readbacks), len(readbacks)),
        "rollback_success_rate": _trial_result(sum(result.rollback_succeeded is True for result in rollbacks), len(rollbacks)),
        "undo_success_rate": _trial_result(int(undo_ok), 1),
        "duplicate_interception_rate": _trial_result(sum(result.duplicate_detected is True and not result.executed for result in duplicates), len(duplicates)),
        "conflict_detection_rate": _trial_result(sum(result.conflict_detected is True and not result.executed for result in conflicts), len(conflicts)),
        "idempotency_success_rate": _trial_result(int(idem_ok), 1),
        "notes": "全部为隔离内存日历故障注入或确定性试验；未访问真实 Google Calendar。",
    }
