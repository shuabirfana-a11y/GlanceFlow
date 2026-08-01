from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from glanceflow.calendar.models import CalendarEventSnapshot, CreateEventRequest
from glanceflow.calendar.port import (
    CalendarEventNotFound,
    CalendarProviderError,
    CalendarTransientError,
)


GOOGLE_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


class GoogleCalendarProvider:
    """Google Calendar adapter; core transaction semantics remain provider-neutral."""

    provider_name = "google-calendar"

    def __init__(self, service: Any, calendar_id: str) -> None:
        if not calendar_id or calendar_id.casefold() == "primary":
            raise ValueError("必须显式配置专用测试日历 ID，Stage 3 禁止使用 primary。")
        self._service = service
        self.calendar_id = calendar_id

    @classmethod
    def from_environment(cls) -> "GoogleCalendarProvider":
        credential_path = os.environ.get("GLANCEFLOW_GOOGLE_CREDENTIALS")
        calendar_id = os.environ.get("GLANCEFLOW_GOOGLE_CALENDAR_ID")
        if not credential_path or not calendar_id:
            raise CalendarProviderError(
                "缺少 GLANCEFLOW_GOOGLE_CREDENTIALS 或 GLANCEFLOW_GOOGLE_CALENDAR_ID。"
            )
        path = Path(credential_path)
        if not path.is_file():
            raise CalendarProviderError("Google 凭据文件不存在。")
        try:
            import google.auth
            from googleapiclient.discovery import build

            credentials, _ = google.auth.load_credentials_from_file(
                str(path), scopes=[GOOGLE_CALENDAR_SCOPE]
            )
            service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
            return cls(service, calendar_id)
        except CalendarProviderError:
            raise
        except Exception as exc:
            raise CalendarProviderError(
                f"Google Calendar 客户端初始化失败：{type(exc).__name__}"
            ) from exc

    def list_events(self, time_min: datetime, time_max: datetime) -> list[CalendarEventSnapshot]:
        payload = self._execute(
            self._service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                timeMax=time_max.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                singleEvents=True,
                orderBy="startTime",
            )
        )
        snapshots = []
        for item in payload.get("items", []):
            if "dateTime" not in item.get("start", {}) or "dateTime" not in item.get("end", {}):
                continue
            snapshots.append(self._to_snapshot(item))
        return snapshots

    def create_event(
        self, request: CreateEventRequest, idempotency_key: str
    ) -> CalendarEventSnapshot:
        private = {**request.private_metadata, "glanceflow_idempotency_key": idempotency_key}
        existing = self._execute(
            self._service.events().list(
                calendarId=self.calendar_id,
                privateExtendedProperty=[f"glanceflow_idempotency_key={idempotency_key}"],
                singleEvents=True,
                maxResults=1,
            )
        ).get("items", [])
        if existing:
            return self._to_snapshot(existing[0])
        body = {
            "summary": request.title,
            "start": {"dateTime": request.start_time.isoformat(), "timeZone": request.timezone},
            "end": {"dateTime": request.end_time.isoformat(), "timeZone": request.timezone},
            "description": request.description,
            "extendedProperties": {"private": private},
        }
        if request.location:
            body["location"] = request.location
        created = self._execute(
            self._service.events().insert(calendarId=self.calendar_id, body=body)
        )
        return self._to_snapshot(created)

    def get_event(self, event_id: str) -> CalendarEventSnapshot:
        payload = self._execute(
            self._service.events().get(calendarId=self.calendar_id, eventId=event_id)
        )
        return self._to_snapshot(payload)

    def delete_event(self, event_id: str) -> None:
        self._execute(
            self._service.events().delete(calendarId=self.calendar_id, eventId=event_id)
        )

    def _execute(self, request):
        try:
            return request.execute()
        except Exception as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 404:
                raise CalendarEventNotFound("Google Calendar 事件不存在。") from exc
            if status == 429 or (isinstance(status, int) and status >= 500):
                raise CalendarTransientError(
                    f"Google Calendar 暂时不可用（HTTP {status}）。"
                ) from exc
            raise CalendarProviderError(
                f"Google Calendar 操作失败（{type(exc).__name__}）。"
            ) from exc

    def _to_snapshot(self, item: dict[str, Any]) -> CalendarEventSnapshot:
        try:
            start = item["start"]
            end = item["end"]
            updated = item.get("updated")
            return CalendarEventSnapshot(
                event_id=item["id"],
                title=item.get("summary", ""),
                start_time=datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")),
                end_time=datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00")),
                timezone=start.get("timeZone") or end.get("timeZone") or "UTC",
                location=item.get("location"),
                description=item.get("description", ""),
                private_metadata=dict(
                    item.get("extendedProperties", {}).get("private", {})
                ),
                provider_name=self.provider_name,
                provider_updated_at=(
                    datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    if updated
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CalendarProviderError("Google Calendar 返回了不完整的定时事件。") from exc

