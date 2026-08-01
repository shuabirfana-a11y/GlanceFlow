from __future__ import annotations

from datetime import timezone
from typing import Any

from glanceflow.calendar.models import (
    CalendarEventSnapshot,
    CreateEventRequest,
    FieldVerificationResult,
    ReadbackVerificationResult,
)


def _instant(value):
    return value.astimezone(timezone.utc)


def verify_readback(
    expected: CreateEventRequest,
    actual: CalendarEventSnapshot,
) -> ReadbackVerificationResult:
    comparisons: list[tuple[str, Any, Any, bool]] = [
        ("title", expected.title, actual.title, expected.title == actual.title),
        ("start_time", expected.start_time, actual.start_time, _instant(expected.start_time) == _instant(actual.start_time)),
        ("end_time", expected.end_time, actual.end_time, _instant(expected.end_time) == _instant(actual.end_time)),
        ("timezone", expected.timezone, actual.timezone, expected.timezone == actual.timezone),
        ("location", expected.location or "", actual.location or "", (expected.location or "") == (actual.location or "")),
    ]
    for key, expected_value in (
        ("notice_package_id", expected.notice_package_id),
        ("transaction_id", expected.transaction_id),
        ("event_role", expected.event_role.value),
    ):
        actual_value = actual.private_metadata.get(key)
        comparisons.append((key, expected_value, actual_value, expected_value == actual_value))

    results = [
        FieldVerificationResult(field_name=name, expected=expected_value, actual=actual_value, passed=passed)
        for name, expected_value, actual_value, passed in comparisons
    ]
    mismatches = [result.field_name for result in results if not result.passed]
    return ReadbackVerificationResult(
        event_id=actual.event_id,
        passed=not mismatches,
        field_results=results,
        expected_snapshot=expected.model_dump(mode="json"),
        actual_snapshot=actual.model_dump(mode="json"),
        mismatch_fields=mismatches,
        message="回读关键字段全部一致。" if not mismatches else f"回读字段不一致：{', '.join(mismatches)}",
    )

