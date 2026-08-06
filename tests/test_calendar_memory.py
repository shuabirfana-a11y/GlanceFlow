from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.calendar.port import (
    CalendarConflictError,
    CalendarEventNotFound,
    CalendarProviderError,
    CalendarTransientError,
)


START = datetime.fromisoformat("2026-08-07T14:00:00+08:00")


def request(transaction_id="GF-TX-0001", role=EventRole.MAIN_EVENT):
    return CreateEventRequest(
        title="创新创业竞赛宣讲",
        start_time=START,
        end_time=START + timedelta(hours=1),
        timezone="Asia/Shanghai",
        location="科技馆报告厅",
        description="GlanceFlow创建的测试事件",
        private_metadata={
            "notice_package_id": "GF-PKG-0001",
            "transaction_id": transaction_id,
            "event_role": role.value,
        },
        notice_package_id="GF-PKG-0001",
        transaction_id=transaction_id,
        event_role=role,
    )


def test_memory_create_read_list_delete():
    provider = MemoryCalendarProvider()
    planned = request()
    created = provider.create_event(planned, "tx-1:main")
    assert created.event_id == planned.event_id
    assert provider.get_event(created.event_id) == created
    assert [event.event_id for event in provider.list_events(START, START + timedelta(hours=2))] == [created.event_id]
    assert provider.list_events(START + timedelta(hours=2), START + timedelta(hours=3)) == []
    provider.delete_event(created.event_id)
    assert provider.event_count == 0
    with pytest.raises(CalendarEventNotFound):
        provider.get_event(created.event_id)


def test_memory_idempotency_key_returns_stable_event():
    provider = MemoryCalendarProvider()
    first = provider.create_event(request(), "same-key")
    second = provider.create_event(request(), "same-key")
    assert first.event_id == second.event_id
    assert provider.event_count == 1


def test_memory_event_id_collision_is_not_treated_as_idempotent_success():
    provider = MemoryCalendarProvider()
    planned = request()
    provider.create_event(planned, "first-key")
    changed = planned.model_copy(update={"title": "unrelated event"})
    with pytest.raises(CalendarConflictError):
        provider.create_event(changed, "different-key")
    assert provider.get_event(planned.event_id).title == planned.title


def test_create_failure_injection():
    provider = MemoryCalendarProvider(MemoryFaultPlan(fail_create_on_calls={1}))
    with pytest.raises(CalendarProviderError, match="call 1"):
        provider.create_event(request(), "key")
    assert provider.event_count == 0


def test_timeout_after_create_is_idempotently_recoverable():
    provider = MemoryCalendarProvider(MemoryFaultPlan(timeout_after_create_on_calls={1}))
    with pytest.raises(CalendarTransientError):
        provider.create_event(request(), "timeout-key")
    assert provider.event_count == 1
    recovered = provider.create_event(request(), "timeout-key")
    assert recovered.event_id == provider.event_ids[0]
    assert provider.event_count == 1


def test_readback_tamper_and_delete_failure_injection():
    faults = MemoryFaultPlan(
        tamper_readback_by_role={"MAIN_EVENT": {"title": "被供应商篡改的标题"}},
        fail_delete_on_calls={1},
    )
    provider = MemoryCalendarProvider(faults)
    created = provider.create_event(request(), "key")
    assert provider.get_event(created.event_id).title == "被供应商篡改的标题"
    with pytest.raises(CalendarProviderError, match="delete failure"):
        provider.delete_event(created.event_id)
    assert provider.event_count == 1


def test_request_rejects_mismatched_private_transaction_metadata():
    invalid = request().model_dump()
    invalid["private_metadata"]["transaction_id"] = "wrong"
    with pytest.raises(ValidationError, match="transaction_id"):
        CreateEventRequest.model_validate(invalid)
