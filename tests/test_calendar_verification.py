from datetime import datetime, timedelta

import pytest

from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.calendar.verification import verify_readback


START = datetime.fromisoformat("2026-08-07T14:00:00+08:00")


def request():
    return CreateEventRequest(
        title="创新创业竞赛宣讲",
        start_time=START,
        end_time=START + timedelta(hours=1),
        timezone="Asia/Shanghai",
        location="科技馆报告厅",
        description="description may be reformatted",
        private_metadata={"notice_package_id": "GF-PKG-0001", "transaction_id": "GF-TX-1", "event_role": "MAIN_EVENT"},
        notice_package_id="GF-PKG-0001",
        transaction_id="GF-TX-1",
        event_role=EventRole.MAIN_EVENT,
    )


def test_all_critical_readback_fields_match():
    provider = MemoryCalendarProvider()
    actual = provider.create_event(request(), "key")
    result = verify_readback(request(), actual)
    assert result.passed is True
    assert result.mismatch_fields == []
    assert all(field.passed for field in result.field_results)


@pytest.mark.parametrize(
    ("field", "change"),
    [
        ("title", {"title": "错误标题"}),
        ("start_time", {"start_time": START + timedelta(minutes=1)}),
        ("end_time", {"end_time": START + timedelta(hours=2)}),
        ("location", {"location": "错误地点"}),
        ("timezone", {"timezone": "UTC"}),
        ("transaction_id", {"private_metadata": {"notice_package_id": "GF-PKG-0001", "transaction_id": "wrong", "event_role": "MAIN_EVENT"}}),
        ("notice_package_id", {"private_metadata": {"notice_package_id": "wrong", "transaction_id": "GF-TX-1", "event_role": "MAIN_EVENT"}}),
        ("event_role", {"private_metadata": {"notice_package_id": "GF-PKG-0001", "transaction_id": "GF-TX-1", "event_role": "DEADLINE_EVENT"}}),
    ],
)
def test_critical_readback_mismatch_is_detected(field, change):
    provider = MemoryCalendarProvider()
    actual = provider.create_event(request(), "key").model_copy(update=change, deep=True)
    result = verify_readback(request(), actual)
    assert result.passed is False
    assert field in result.mismatch_fields


def test_same_instant_with_different_offset_is_not_time_mismatch():
    provider = MemoryCalendarProvider()
    actual = provider.create_event(request(), "key")
    actual = actual.model_copy(
        update={
            "start_time": datetime.fromisoformat("2026-08-07T06:00:00+00:00"),
            "end_time": datetime.fromisoformat("2026-08-07T07:00:00+00:00"),
        }
    )
    result = verify_readback(request(), actual)
    assert result.passed is True

