from __future__ import annotations

from glanceflow.calendar.models import RollbackResult, UndoResult
from glanceflow.calendar.port import CalendarEventNotFound, CalendarPort


def _delete_and_verify(provider: CalendarPort, event_id: str) -> tuple[bool, bool, str | None]:
    delete_succeeded = False
    error_message = None
    try:
        provider.delete_event(event_id)
        delete_succeeded = True
    except CalendarEventNotFound:
        delete_succeeded = True
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"

    try:
        provider.get_event(event_id)
        absence_verified = False
    except CalendarEventNotFound:
        absence_verified = True
    except Exception as exc:
        absence_verified = False
        verification_error = f"{type(exc).__name__}: {exc}"
        error_message = f"{error_message}; {verification_error}" if error_message else verification_error
    return delete_succeeded, absence_verified, error_message


def rollback_events(provider: CalendarPort, event_ids: list[str]) -> list[RollbackResult]:
    results = []
    for event_id in reversed(event_ids):
        deleted, absent, error = _delete_and_verify(provider, event_id)
        results.append(
            RollbackResult(
                event_id=event_id,
                delete_succeeded=deleted,
                absence_verified=absent,
                error_message=error,
            )
        )
    return results


def undo_events(provider: CalendarPort, event_ids: list[str]) -> list[UndoResult]:
    results = []
    for event_id in reversed(event_ids):
        deleted, absent, error = _delete_and_verify(provider, event_id)
        results.append(
            UndoResult(
                event_id=event_id,
                delete_succeeded=deleted,
                absence_verified=absent,
                error_message=error,
            )
        )
    return results

