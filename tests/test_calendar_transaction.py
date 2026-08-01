import pytest

from glanceflow.application.scheduling_service import SchedulingValidationError
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import TransactionStatus
from glanceflow.calendar.port import CalendarTransientError
from glanceflow.calendar.transaction import TransactionStateError


def confirm_and_execute(service, confirmation_factory, transaction_id, accepted_conflict=False):
    record = service.get_transaction(transaction_id)
    service.confirm(
        transaction_id,
        confirmation_factory(record, accepted_conflict=accepted_conflict),
    )
    return service.execute(transaction_id)


def test_single_event_transaction_verified(scheduling_factory, confirmation_factory):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-SINGLE")
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-SINGLE")
    assert record.status is TransactionStatus.VERIFIED
    assert record.created_event_ids == ["mem-event-0001"]
    assert provider.event_ids == ["mem-event-0001"]
    assert record.verification_results[0].passed is True
    assert {event.action for event in record.audit_events} >= {
        "USER_CONFIRMED",
        "EVENT_CREATED",
        "READBACK_VERIFIED",
        "TRANSACTION_VERIFIED",
    }


def test_two_event_package_is_verified_atomically(scheduling_factory, confirmation_factory):
    service, provider, *_ = scheduling_factory(with_deadline=True, transaction_id="GF-TX-DOUBLE")
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-DOUBLE")
    assert record.status is TransactionStatus.VERIFIED
    assert record.created_event_ids == ["mem-event-0001", "mem-event-0002"]
    assert provider.event_count == 2
    assert [item.passed for item in record.verification_results] == [True, True]


def test_second_event_failure_rolls_back_first(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_create_on_calls={2}))
    service, provider, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id="GF-TX-SECOND-FAIL"
    )
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-SECOND-FAIL")
    assert record.status is TransactionStatus.ROLLED_BACK
    assert record.created_event_ids == ["mem-event-0001"]
    assert provider.event_count == 0
    assert record.rollback_results[0].event_id == "mem-event-0001"
    assert record.rollback_results[0].absence_verified is True
    assert "TRANSACTION_VERIFIED" not in {event.action for event in record.audit_events}


def test_readback_mismatch_rolls_back_all(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(
        MemoryFaultPlan(tamper_readback_by_role={"DEADLINE_EVENT": {"title": "错误截止标题"}})
    )
    service, provider, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id="GF-TX-TAMPER"
    )
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-TAMPER")
    assert record.status is TransactionStatus.ROLLED_BACK
    assert provider.event_count == 0
    assert record.verification_results[1].mismatch_fields == ["title"]
    assert {item.event_id for item in record.rollback_results} == {"mem-event-0001", "mem-event-0002"}


def test_readback_provider_failure_rolls_back_all(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_get_on_calls={1}))
    service, provider, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id="GF-TX-READ-FAIL"
    )
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-READ-FAIL")
    assert record.status is TransactionStatus.ROLLED_BACK
    assert provider.event_count == 0
    assert record.verification_results == []
    assert "READBACK_FAILED" in {event.action for event in record.audit_events}


def test_rollback_failure_is_not_hidden(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(
        MemoryFaultPlan(fail_create_on_calls={2}, fail_delete_on_calls={1})
    )
    service, provider, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id="GF-TX-ROLLBACK-FAIL"
    )
    record = confirm_and_execute(service, confirmation_factory, "GF-TX-ROLLBACK-FAIL")
    assert record.status is TransactionStatus.FAILED
    assert provider.event_ids == ["mem-event-0001"]
    assert record.rollback_results[0].delete_succeeded is False
    assert record.rollback_results[0].absence_verified is False
    assert record.audit_events[-1].action == "ROLLBACK_FAILED"
    assert record.audit_events[-1].details["remaining_event_ids"] == ["mem-event-0001"]


def test_timeout_after_create_retries_without_duplicate(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(MemoryFaultPlan(timeout_after_create_on_calls={1}))
    service, provider, *_ = scheduling_factory(provider=provider, transaction_id="GF-TX-TIMEOUT")
    record = service.get_transaction("GF-TX-TIMEOUT")
    service.confirm("GF-TX-TIMEOUT", confirmation_factory(record))
    with pytest.raises(CalendarTransientError):
        service.execute("GF-TX-TIMEOUT")
    assert provider.event_count == 1
    assert service.get_transaction("GF-TX-TIMEOUT").status is TransactionStatus.CONFIRMED

    recovered = service.execute("GF-TX-TIMEOUT")
    assert recovered.status is TransactionStatus.VERIFIED
    assert recovered.created_event_ids == ["mem-event-0001"]
    assert provider.event_count == 1


def test_second_event_timeout_retries_two_event_package_without_duplicates(
    scheduling_factory, confirmation_factory
):
    provider = MemoryCalendarProvider(MemoryFaultPlan(timeout_after_create_on_calls={2}))
    service, provider, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id="GF-TX-SECOND-TIMEOUT"
    )
    record = service.get_transaction("GF-TX-SECOND-TIMEOUT")
    service.confirm("GF-TX-SECOND-TIMEOUT", confirmation_factory(record))
    with pytest.raises(CalendarTransientError):
        service.execute("GF-TX-SECOND-TIMEOUT")
    assert provider.event_ids == ["mem-event-0001", "mem-event-0002"]
    assert service.get_transaction("GF-TX-SECOND-TIMEOUT").created_event_ids == ["mem-event-0001"]

    recovered = service.execute("GF-TX-SECOND-TIMEOUT")
    assert recovered.status is TransactionStatus.VERIFIED
    assert recovered.created_event_ids == ["mem-event-0001", "mem-event-0002"]
    assert provider.event_count == 2


def test_verified_transaction_cannot_execute_again(scheduling_factory, confirmation_factory):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-NO-REPEAT")
    confirm_and_execute(service, confirmation_factory, "GF-TX-NO-REPEAT")
    with pytest.raises(TransactionStateError, match="禁止重复执行"):
        service.execute("GF-TX-NO-REPEAT")
    assert provider.event_count == 1


def test_rolled_back_package_requires_new_transaction_and_confirmation(
    draft_factory, confirmation_factory
):
    from glanceflow.application.scheduling_service import TrustedSchedulingService
    from glanceflow.safety.gate import evaluate_notice

    draft = draft_factory(with_deadline=True)
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_create_on_calls={2}))
    first_service = TrustedSchedulingService(provider)
    first_service.preflight(draft, evaluate_notice(draft), transaction_id="GF-TX-OLD")
    first = first_service.get_transaction("GF-TX-OLD")
    first_service.confirm("GF-TX-OLD", confirmation_factory(first))
    rolled_back = first_service.execute("GF-TX-OLD")
    assert rolled_back.status is TransactionStatus.ROLLED_BACK
    assert provider.event_count == 0
    with pytest.raises(TransactionStateError):
        first_service.execute("GF-TX-OLD")

    provider.fault_plan.fail_create_on_calls.clear()
    second_service = TrustedSchedulingService(provider)
    second_service.preflight(draft, evaluate_notice(draft), transaction_id="GF-TX-NEW")
    with pytest.raises(TransactionStateError, match="WAITING_CONFIRMATION"):
        second_service.execute("GF-TX-NEW")
    second = second_service.get_transaction("GF-TX-NEW")
    second_service.confirm("GF-TX-NEW", confirmation_factory(second))
    verified = second_service.execute("GF-TX-NEW")
    assert verified.status is TransactionStatus.VERIFIED
    assert verified.transaction_id == "GF-TX-NEW"
    assert provider.event_count == 2
