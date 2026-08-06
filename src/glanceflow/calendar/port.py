from datetime import datetime
from typing import Protocol

from glanceflow.calendar.models import CalendarEventSnapshot, CreateEventRequest


class CalendarError(RuntimeError):
    """Base structured calendar boundary error."""


class CalendarProviderError(CalendarError):
    pass


class CalendarTransientError(CalendarProviderError):
    """Retryable provider uncertainty such as timeout after submission."""


class CalendarAuthorizationError(CalendarProviderError):
    pass


class CalendarPermissionError(CalendarProviderError):
    pass


class CalendarConflictError(CalendarProviderError):
    pass


class CalendarRateLimitError(CalendarTransientError):
    pass


class CalendarServerError(CalendarTransientError):
    pass


class CalendarEventNotFound(CalendarError):
    pass


class CalendarPort(Protocol):
    provider_name: str
    calendar_id: str

    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEventSnapshot]: ...

    def create_event(
        self, request: CreateEventRequest, idempotency_key: str
    ) -> CalendarEventSnapshot: ...

    def get_event(self, event_id: str) -> CalendarEventSnapshot: ...

    def delete_event(self, event_id: str) -> None: ...
