from datetime import datetime, timedelta

import pytest

from glanceflow.calendar.google_provider import GoogleCalendarProvider
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.calendar.port import CalendarEventNotFound, CalendarProviderError


class FakeRequest:
    def __init__(self, callback):
        self.callback = callback

    def execute(self):
        return self.callback()


class FakeGoogleEvents:
    def __init__(self):
        self.items = {}
        self.calls = []
        self.next_id = 1

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))

        def execute():
            private_filter = kwargs.get("privateExtendedProperty")
            if private_filter:
                key, value = private_filter[0].split("=", 1)
                matches = [
                    item for item in self.items.values()
                    if item.get("extendedProperties", {}).get("private", {}).get(key) == value
                ]
                return {"items": matches[: kwargs.get("maxResults", len(matches))]}
            return {"items": list(self.items.values())}

        return FakeRequest(execute)

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))

        def execute():
            event_id = f"google-event-{self.next_id:04d}"
            self.next_id += 1
            item = {
                "id": event_id,
                "updated": "2026-08-01T01:00:00Z",
                **kwargs["body"],
            }
            self.items[event_id] = item
            return item

        return FakeRequest(execute)

    def get(self, **kwargs):
        self.calls.append(("get", kwargs))

        def execute():
            try:
                return self.items[kwargs["eventId"]]
            except KeyError as exc:
                error = RuntimeError("not found")
                error.resp = type("Response", (), {"status": 404})()
                raise error from exc

        return FakeRequest(execute)

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))

        def execute():
            if kwargs["eventId"] not in self.items:
                error = RuntimeError("not found")
                error.resp = type("Response", (), {"status": 404})()
                raise error
            del self.items[kwargs["eventId"]]
            return None

        return FakeRequest(execute)


class FakeGoogleService:
    def __init__(self):
        self.resource = FakeGoogleEvents()

    def events(self):
        return self.resource


START = datetime.fromisoformat("2026-08-07T14:00:00+08:00")


def request():
    return CreateEventRequest(
        title="创新创业竞赛宣讲",
        start_time=START,
        end_time=START + timedelta(hours=1),
        timezone="Asia/Shanghai",
        location="科技馆报告厅",
        description="测试描述",
        private_metadata={"notice_package_id": "GF-PKG-0001", "transaction_id": "GF-TX-1", "event_role": "MAIN_EVENT"},
        notice_package_id="GF-PKG-0001",
        transaction_id="GF-TX-1",
        event_role=EventRole.MAIN_EVENT,
    )


def test_google_contract_create_read_list_delete_and_private_metadata():
    service = FakeGoogleService()
    provider = GoogleCalendarProvider(service, "test-calendar@example.com")
    created = provider.create_event(request(), "idempotency-1")
    assert created.event_id == "google-event-0001"
    assert created.private_metadata["notice_package_id"] == "GF-PKG-0001"
    assert created.private_metadata["transaction_id"] == "GF-TX-1"
    assert created.private_metadata["event_role"] == "MAIN_EVENT"
    assert created.private_metadata["glanceflow_idempotency_key"] == "idempotency-1"
    assert provider.get_event(created.event_id).title == request().title
    assert [item.event_id for item in provider.list_events(START, START + timedelta(hours=2))] == [created.event_id]
    provider.delete_event(created.event_id)
    with pytest.raises(CalendarEventNotFound):
        provider.get_event(created.event_id)


def test_google_contract_project_idempotency_avoids_second_insert():
    service = FakeGoogleService()
    provider = GoogleCalendarProvider(service, "test-calendar@example.com")
    first = provider.create_event(request(), "same-key")
    second = provider.create_event(request(), "same-key")
    assert first.event_id == second.event_id
    assert len([call for call in service.resource.calls if call[0] == "insert"]) == 1


def test_google_contract_refuses_primary_calendar():
    with pytest.raises(ValueError, match="primary"):
        GoogleCalendarProvider(FakeGoogleService(), "primary")


def test_google_credentials_are_not_optional_or_logged(monkeypatch):
    monkeypatch.delenv("GLANCEFLOW_GOOGLE_CREDENTIALS", raising=False)
    monkeypatch.delenv("GLANCEFLOW_GOOGLE_CALENDAR_ID", raising=False)
    with pytest.raises(CalendarProviderError) as exc_info:
        GoogleCalendarProvider.from_environment()
    assert "GLANCEFLOW_GOOGLE_CREDENTIALS" in str(exc_info.value)
    assert "token" not in str(exc_info.value).casefold()

