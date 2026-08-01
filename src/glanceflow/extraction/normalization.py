from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo


DATE_PATTERN = re.compile(r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?")
TIME_PATTERN = re.compile(r"(?<!\d)(?P<hour>[01]?\d|2[0-3])\s*:\s*(?P<minute>[0-5]\d)(?!\d)")
WEEKDAY_PATTERN = re.compile(r"(?:星期|周)\s*[一二三四五六日天]")
RELATIVE_TIME_PATTERN = re.compile(r"(?:周[一二三四五六日天](?:上午|下午|晚上)?|近期|稍后|月底前|明天|后天)")


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def parse_datetime_text(value: str, timezone: str) -> tuple[datetime, str, str | None] | None:
    text = normalize_text(value)
    date_match = DATE_PATTERN.search(text)
    time_match = TIME_PATTERN.search(text)
    if not date_match or not time_match:
        return None
    try:
        parsed = datetime(
            int(date_match.group("year")),
            int(date_match.group("month")),
            int(date_match.group("day")),
            int(time_match.group("hour")),
            int(time_match.group("minute")),
            tzinfo=ZoneInfo(timezone),
        )
    except ValueError:
        return None
    weekday = WEEKDAY_PATTERN.search(text)
    return parsed, date_match.group(0), weekday.group(0) if weekday else None


def find_relative_time(value: str) -> str | None:
    match = RELATIVE_TIME_PATTERN.search(normalize_text(value))
    return match.group(0) if match else None


def strip_label(value: str, labels: tuple[str, ...]) -> str:
    text = normalize_text(value)
    for label in labels:
        match = re.match(rf"^{re.escape(label)}\s*[:：]?\s*(.+)$", text)
        if match:
            return match.group(1).strip()
    return ""

