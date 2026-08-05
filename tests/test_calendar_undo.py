import pytest

from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import TransactionStatus
from glanceflow.calendar.transaction import TransactionStateError


def verified_record(scheduling_factory, confirmation_factory, *, provider=None, tx="GF-TX-UNDO"):
    service, calendar, *_ = scheduling_factory(
        with_deadline=True, provider=provider, transaction_id=tx
    )
    current = service.get_transaction(tx)
    service.confirm(tx, confirmation_factory(current))
    return service, calendar, service.execute(tx)


def test_precise_undo_removes_all_transaction_events(scheduling_factory, confirmation_factory):
    service, provider, verified = verified_record(scheduling_factory, confirmation_factory)
    assert verified.created_event_ids == ["mem-event-0001", "mem-event-0002"]
    undone = service.undo("GF-TX-UNDO")
    assert undone.status is TransactionStatus.UNDONE
    assert provider.event_count == 0
    assert all(item.absence_verified for item in undone.undo_results)
    assert all(item.calendar_id == provider.calendar_id for item in undone.undo_results)
    assert undone.audit_events[-1].action == "UNDO_COMPLETED"


def test_partial_undo_failure_preserves_remaining_event_id(scheduling_factory, confirmation_factory):
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_delete_on_calls={1}))
    service, provider, _ = verified_record(
        scheduling_factory, confirmation_factory, provider=provider, tx="GF-TX-PARTIAL-UNDO"
    )
    result = service.undo("GF-TX-PARTIAL-UNDO")
    assert result.status is TransactionStatus.FAILED
    assert provider.event_ids == ["mem-event-0002"]
    assert result.audit_events[-1].action == "UNDO_FAILED"
    assert result.audit_events[-1].details["remaining_event_ids"] == ["mem-event-0002"]


def test_repeated_undo_is_safe_noop(scheduling_factory, confirmation_factory):
    service, provider, _ = verified_record(
        scheduling_factory, confirmation_factory, tx="GF-TX-REPEAT-UNDO"
    )
    first = service.undo("GF-TX-REPEAT-UNDO")
    second = service.undo("GF-TX-REPEAT-UNDO")
    assert first.status is second.status is TransactionStatus.UNDONE
    assert provider.event_count == 0
    assert second.audit_events[-1].action == "UNDO_ALREADY_COMPLETED"


def test_undo_does_not_delete_same_title_unrelated_event(
    scheduling_factory, confirmation_factory
):
    service, provider, verified = verified_record(
        scheduling_factory, confirmation_factory, tx="GF-TX-PRECISE"
    )
    unrelated_request = verified.planned_requests[0].model_copy(
        update={
            "transaction_id": "unrelated",
            "notice_package_id": "unrelated-package",
            "private_metadata": {
                "transaction_id": "unrelated",
                "notice_package_id": "unrelated-package",
                "event_role": "MAIN_EVENT",
            },
        }
    )
    unrelated = provider.create_event(unrelated_request, "unrelated-key")
    result = service.undo("GF-TX-PRECISE")
    assert result.status is TransactionStatus.UNDONE
    assert provider.event_ids == [unrelated.event_id]
    assert provider.get_event(unrelated.event_id).title == verified.planned_requests[0].title


def test_non_verified_transaction_cannot_be_undone(
    scheduling_factory, confirmation_factory
):
    service, provider, *_ = scheduling_factory(transaction_id="GF-TX-NOT-VERIFIED")
    with pytest.raises(TransactionStateError, match="仅 VERIFIED"):
        service.undo("GF-TX-NOT-VERIFIED")
    assert provider.event_count == 0


def test_undo_rejects_calendar_binding_mismatch(scheduling_factory, confirmation_factory):
    service, provider, _ = verified_record(
        scheduling_factory, confirmation_factory, tx="GF-TX-CALENDAR-MISMATCH"
    )
    service._records["GF-TX-CALENDAR-MISMATCH"].calendar_id = "memory://different-calendar"
    with pytest.raises(ValueError, match="calendar_id"):
        service.undo("GF-TX-CALENDAR-MISMATCH")
    assert provider.event_count == 2
