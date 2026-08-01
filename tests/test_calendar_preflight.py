from datetime import datetime, timedelta

from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.calendar.preflight import check_conflict, check_duplicate


START = datetime.fromisoformat("2026-08-07T14:00:00+08:00")


def make_request(title="创新创业竞赛宣讲", role=EventRole.MAIN_EVENT, transaction="GF-TX-0001"):
    return CreateEventRequest(
        title=title,
        start_time=START,
        end_time=START + timedelta(hours=1),
        timezone="Asia/Shanghai",
        location="科技馆报告厅",
        description="测试",
        private_metadata={
            "notice_package_id": "GF-PKG-0001",
            "transaction_id": transaction,
            "event_role": role.value,
        },
        notice_package_id="GF-PKG-0001",
        transaction_id=transaction,
        event_role=role,
    )


def test_duplicate_existing_activity_is_blocked():
    provider = MemoryCalendarProvider()
    provider.create_event(make_request(transaction="old-tx"), "old-key")
    result = check_duplicate(provider, make_request(transaction="new-tx"))
    assert result.is_duplicate is True
    assert result.matching_events[0].event_id == "mem-event-0001"
    assert "notice_package_id" in result.comparison_basis
    assert "normalized_title_and_start_time" in result.comparison_basis


def test_main_and_deadline_roles_are_not_misclassified_as_duplicates():
    provider = MemoryCalendarProvider()
    provider.create_event(make_request(role=EventRole.MAIN_EVENT), "main-key")
    deadline = make_request(title="【截止】完成竞赛报名", role=EventRole.DEADLINE_EVENT)
    result = check_duplicate(provider, deadline)
    assert result.is_duplicate is False
    assert result.matching_events == []


def test_conflict_reports_title_times_and_overlap():
    provider = MemoryCalendarProvider()
    existing = make_request(title="线性代数", transaction="course")
    existing = existing.model_copy(
        update={
            "start_time": START + timedelta(minutes=30),
            "end_time": START + timedelta(minutes=90),
            "notice_package_id": "external",
            "private_metadata": {"event_role": "MAIN_EVENT", "transaction_id": "course", "notice_package_id": "external"},
        }
    )
    provider.create_event(existing, "course-key")
    result = check_conflict(provider, make_request())
    assert result.has_conflict is True
    assert result.conflicting_events[0].title == "线性代数"
    assert result.conflicting_events[0].start_time == START + timedelta(minutes=30)
    assert result.overlap_minutes == 30


def test_deadline_event_does_not_trigger_strong_conflict():
    provider = MemoryCalendarProvider()
    provider.create_event(make_request(), "main-key")
    result = check_conflict(provider, make_request(role=EventRole.DEADLINE_EVENT))
    assert result.has_conflict is False
    assert result.overlap_minutes == 0

