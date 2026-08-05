from datetime import timedelta

import pytest

from glanceflow.application.scheduling_service import SchedulingValidationError, TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.calendar.models import CreateEventRequest, EventRole, TransactionStatus
from glanceflow.domain.enums import SafetyGateStatus


def test_non_ready_draft_cannot_enter_transaction(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.location = ""
    from glanceflow.safety.gate import evaluate_notice

    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    service = TrustedSchedulingService(MemoryCalendarProvider())
    with pytest.raises(SchedulingValidationError, match="READY_TO_CONFIRM"):
        service.preflight(draft, decision, transaction_id="GF-TX-NOT-READY")


def test_unconfirmed_transaction_creates_nothing(scheduling_factory, confirmation_factory):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-NO-CONFIRM")
    record = service.get_transaction("GF-TX-NO-CONFIRM")
    with pytest.raises(SchedulingValidationError, match="未明确确认"):
        service.confirm("GF-TX-NO-CONFIRM", confirmation_factory(record, confirmed=False))
    assert provider.event_count == 0
    assert service.get_transaction("GF-TX-NO-CONFIRM").status is TransactionStatus.WAITING_CONFIRMATION


@pytest.mark.parametrize(
    ("field", "change"),
    [
        ("title", {"confirmed_title": "错误标题"}),
        ("event_start", {"confirmed_event_start": "2026-08-07T15:00:00+08:00"}),
        ("location", {"confirmed_location": "错误地点"}),
        ("deadline", {"confirmed_deadline": "2026-08-05T20:00:00+08:00"}),
    ],
)
def test_confirmation_field_mismatch_rejected(
    scheduling_factory, confirmation_factory, field, change
):
    with_deadline = field == "deadline"
    service, provider, *_ = scheduling_factory(
        with_deadline=with_deadline, transaction_id=f"GF-TX-MISMATCH-{field}"
    )
    record = service.get_transaction(f"GF-TX-MISMATCH-{field}")
    with pytest.raises(SchedulingValidationError, match=field):
        service.confirm(
            f"GF-TX-MISMATCH-{field}", confirmation_factory(record, **change)
        )
    assert provider.event_count == 0


def add_conflicting_course(provider, start):
    request = CreateEventRequest(
        title="线性代数",
        start_time=start + timedelta(minutes=30),
        end_time=start + timedelta(minutes=90),
        timezone="Asia/Shanghai",
        location="教学楼101",
        description="用户已有课程",
        private_metadata={"notice_package_id": "external", "transaction_id": "course", "event_role": "MAIN_EVENT"},
        notice_package_id="external",
        transaction_id="course",
        event_role=EventRole.MAIN_EVENT,
    )
    provider.create_event(request, "external-course")


def test_conflict_requires_second_explicit_confirmation(
    draft_factory, confirmation_factory
):
    draft = draft_factory()
    from glanceflow.safety.gate import evaluate_notice

    provider = MemoryCalendarProvider()
    add_conflicting_course(provider, draft.main_event.event_start)
    service = TrustedSchedulingService(provider)
    preflight = service.preflight(
        draft, evaluate_notice(draft), transaction_id="GF-TX-CONFLICT"
    )
    assert preflight.conflict_result.has_conflict is True
    assert preflight.conflict_result.overlap_minutes == 30
    record = service.get_transaction("GF-TX-CONFLICT")
    with pytest.raises(SchedulingValidationError, match="accepted_conflict=True"):
        service.confirm("GF-TX-CONFLICT", confirmation_factory(record))
    assert provider.event_count == 1

    confirmed = service.confirm(
        "GF-TX-CONFLICT",
        confirmation_factory(record, accepted_conflict=True),
    )
    assert confirmed.status is TransactionStatus.CONFIRMED
    executed = service.execute("GF-TX-CONFLICT")
    assert executed.status is TransactionStatus.VERIFIED
    assert provider.event_count == 2


def test_preflight_provider_failure_records_failed_without_creation(draft_factory):
    from glanceflow.calendar.memory_provider import MemoryFaultPlan
    from glanceflow.safety.gate import evaluate_notice

    draft = draft_factory()
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_list=True))
    service = TrustedSchedulingService(provider)
    with pytest.raises(SchedulingValidationError, match="预检失败"):
        service.preflight(draft, evaluate_notice(draft), transaction_id="GF-TX-PREFLIGHT-FAIL")
    record = service.get_transaction("GF-TX-PREFLIGHT-FAIL")
    assert record.status is TransactionStatus.FAILED
    assert record.audit_events[-1].action == "PREFLIGHT_PROVIDER_FAILED"
    assert provider.event_count == 0


def test_confirmation_invalidated_if_planned_field_changes(
    scheduling_factory, confirmation_factory
):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-MUTATED")
    record = service.get_transaction("GF-TX-MUTATED")
    service.confirm("GF-TX-MUTATED", confirmation_factory(record))
    service._records["GF-TX-MUTATED"].planned_requests[0].title = "确认后被修改"
    with pytest.raises(SchedulingValidationError, match="原确认已失效"):
        service.execute("GF-TX-MUTATED")
    assert provider.event_count == 0


def test_confirmation_rejects_different_target_calendar(scheduling_factory, confirmation_factory):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-WRONG-CALENDAR")
    record = service.get_transaction("GF-TX-WRONG-CALENDAR")
    with pytest.raises(SchedulingValidationError, match="calendar_id"):
        service.confirm(
            "GF-TX-WRONG-CALENDAR",
            confirmation_factory(record, confirmed_calendar_id="memory://other-calendar"),
        )
    assert provider.event_count == 0


def test_any_planned_request_change_invalidates_request_hash(
    scheduling_factory, confirmation_factory
):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-REQUEST-HASH")
    record = service.get_transaction("GF-TX-REQUEST-HASH")
    service.confirm("GF-TX-REQUEST-HASH", confirmation_factory(record))
    service._records["GF-TX-REQUEST-HASH"].planned_requests[0].timezone = "UTC"
    with pytest.raises(SchedulingValidationError, match="request_hash"):
        service.execute("GF-TX-REQUEST-HASH")
    assert provider.event_count == 0
