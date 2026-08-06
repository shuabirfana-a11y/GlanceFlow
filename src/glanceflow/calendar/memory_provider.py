from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from glanceflow.calendar.models import CalendarEventSnapshot, CreateEventRequest
from glanceflow.calendar.port import (
    CalendarAuthorizationError,
    CalendarConflictError,
    CalendarEventNotFound,
    CalendarPermissionError,
    CalendarProviderError,
    CalendarRateLimitError,
    CalendarServerError,
    CalendarTransientError,
)


@dataclass
class MemoryFaultPlan:
    fail_create_on_calls: set[int] = field(default_factory=set)
    timeout_before_create_on_calls: set[int] = field(default_factory=set)
    timeout_after_create_on_calls: set[int] = field(default_factory=set)
    fail_get_on_calls: set[int] = field(default_factory=set)
    fail_delete_on_calls: set[int] = field(default_factory=set)
    timeout_after_delete_on_calls: set[int] = field(default_factory=set)
    retain_after_delete_on_calls: set[int] = field(default_factory=set)
    create_http_status_on_calls: dict[int, int] = field(default_factory=dict)
    get_http_status_on_calls: dict[int, int] = field(default_factory=dict)
    delete_http_status_on_calls: dict[int, int] = field(default_factory=dict)
    fail_list: bool = False
    tamper_readback_by_role: dict[str, dict] = field(default_factory=dict)


class MemoryCalendarProvider:
    provider_name = "memory-calendar"
    calendar_id = "memory://glanceflow-local-test"

    def __init__(self, fault_plan: MemoryFaultPlan | None = None) -> None:
        self._events: dict[str, CalendarEventSnapshot] = {}
        self._idempotency: dict[str, str] = {}
        self._create_calls = 0
        self._get_calls = 0
        self._delete_calls = 0
        self.fault_plan = fault_plan or MemoryFaultPlan()

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def event_ids(self) -> list[str]:
        return sorted(self._events)

    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEventSnapshot]:
        if self.fault_plan.fail_list:
            raise CalendarProviderError("memory provider list failure")
        return [
            event.model_copy(deep=True)
            for event in sorted(self._events.values(), key=lambda item: (item.start_time, item.event_id))
            if event.start_time < time_max and event.end_time > time_min
        ]

    def create_event(self, request: CreateEventRequest, idempotency_key: str) -> CalendarEventSnapshot:
        if idempotency_key in self._idempotency:
            event_id = self._idempotency[idempotency_key]
            return self._events[event_id].model_copy(deep=True)
        if request.event_id in self._events:
            raise CalendarConflictError("memory provider event_id already exists")
        self._create_calls += 1
        call = self._create_calls
        self._raise_status(self.fault_plan.create_http_status_on_calls.get(call))
        if call in self.fault_plan.timeout_before_create_on_calls:
            raise CalendarTransientError(f"memory provider timeout before create on call {call}")
        if call in self.fault_plan.fail_create_on_calls:
            raise CalendarProviderError(f"memory provider create failure on call {call}")
        event_id = request.event_id
        snapshot = CalendarEventSnapshot(
            event_id=event_id,
            title=request.title,
            start_time=request.start_time,
            end_time=request.end_time,
            timezone=request.timezone,
            location=request.location,
            description=request.description,
            private_metadata=dict(request.private_metadata),
            provider_name=self.provider_name,
            provider_updated_at=datetime.now(request.start_time.tzinfo),
        )
        self._events[event_id] = snapshot
        self._idempotency[idempotency_key] = event_id
        if call in self.fault_plan.timeout_after_create_on_calls:
            raise CalendarTransientError(f"memory provider timeout after create on call {call}")
        return snapshot.model_copy(deep=True)

    def get_event(self, event_id: str) -> CalendarEventSnapshot:
        self._get_calls += 1
        self._raise_status(self.fault_plan.get_http_status_on_calls.get(self._get_calls))
        if self._get_calls in self.fault_plan.fail_get_on_calls:
            raise CalendarProviderError(f"memory provider get failure on call {self._get_calls}")
        if event_id not in self._events:
            raise CalendarEventNotFound(event_id)
        snapshot = self._events[event_id].model_copy(deep=True)
        role = snapshot.private_metadata.get("event_role", "")
        changes = self.fault_plan.tamper_readback_by_role.get(role)
        if changes:
            snapshot = snapshot.model_copy(update=changes, deep=True)
        return snapshot

    def delete_event(self, event_id: str) -> None:
        self._delete_calls += 1
        call = self._delete_calls
        self._raise_status(self.fault_plan.delete_http_status_on_calls.get(call))
        if call in self.fault_plan.fail_delete_on_calls:
            raise CalendarProviderError(f"memory provider delete failure on call {call}")
        if event_id not in self._events:
            raise CalendarEventNotFound(event_id)
        if call not in self.fault_plan.retain_after_delete_on_calls:
            del self._events[event_id]
        for key, value in list(self._idempotency.items()):
            if value == event_id:
                del self._idempotency[key]
        if call in self.fault_plan.timeout_after_delete_on_calls:
            raise CalendarTransientError(f"memory provider timeout after delete on call {call}")

    @staticmethod
    def _raise_status(status: int | None) -> None:
        if status is None:
            return
        if status == 401:
            raise CalendarAuthorizationError("memory provider HTTP 401")
        if status == 403:
            raise CalendarPermissionError("memory provider HTTP 403")
        if status == 404:
            raise CalendarEventNotFound("memory provider HTTP 404")
        if status == 409:
            raise CalendarConflictError("memory provider HTTP 409")
        if status == 429:
            raise CalendarRateLimitError("memory provider HTTP 429")
        if status >= 500:
            raise CalendarServerError(f"memory provider HTTP {status}")
        raise CalendarProviderError(f"memory provider HTTP {status}")
