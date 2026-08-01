from __future__ import annotations

import unicodedata
from datetime import timedelta, timezone

from glanceflow.calendar.models import ConflictResult, CreateEventRequest, DuplicateResult, EventRole
from glanceflow.calendar.port import CalendarPort
from glanceflow.config import DUPLICATE_TIME_TOLERANCE_MINUTES


def _normalized_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def check_duplicate(provider: CalendarPort, request: CreateEventRequest) -> DuplicateResult:
    tolerance = timedelta(minutes=DUPLICATE_TIME_TOLERANCE_MINUTES)
    candidates = provider.list_events(request.start_time - tolerance, request.end_time + tolerance)
    matches = []
    bases: set[str] = set()
    for event in candidates:
        metadata = event.private_metadata
        existing_role = metadata.get("event_role")
        if existing_role and existing_role != request.event_role.value:
            continue
        evidence = []
        if metadata.get("transaction_id") == request.transaction_id:
            evidence.append("transaction_id")
        if metadata.get("notice_package_id") == request.notice_package_id:
            evidence.append("notice_package_id")
        same_title = _normalized_title(event.title) == _normalized_title(request.title)
        close_time = abs(
            (event.start_time.astimezone(timezone.utc) - request.start_time.astimezone(timezone.utc)).total_seconds()
        ) <= tolerance.total_seconds()
        if same_title and close_time:
            evidence.append("normalized_title_and_start_time")
        if evidence:
            matches.append(event)
            bases.update(evidence)
    return DuplicateResult(
        is_duplicate=bool(matches),
        matching_events=matches,
        comparison_basis=sorted(bases),
        message="发现疑似重复日程，禁止再次创建。" if matches else "未发现重复日程。",
    )


def check_conflict(provider: CalendarPort, request: CreateEventRequest) -> ConflictResult:
    if request.event_role is not EventRole.MAIN_EVENT:
        return ConflictResult(has_conflict=False, message="截止提醒不参与强冲突检查。")
    events = provider.list_events(request.start_time, request.end_time)
    conflicts = []
    overlap_minutes = 0
    for event in events:
        overlap_start = max(request.start_time, event.start_time)
        overlap_end = min(request.end_time, event.end_time)
        if overlap_end > overlap_start:
            conflicts.append(event)
            overlap_minutes += int((overlap_end - overlap_start).total_seconds() // 60)
    return ConflictResult(
        has_conflict=bool(conflicts),
        conflicting_events=conflicts,
        overlap_minutes=overlap_minutes,
        message=(
            f"发现 {len(conflicts)} 个冲突事件，共重叠 {overlap_minutes} 分钟；需要二次明确确认。"
            if conflicts
            else "未发现时间冲突。"
        ),
    )
