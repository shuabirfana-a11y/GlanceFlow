from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PrivacyFinding:
    kind: str
    field: str


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")),
    ("phone", re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")),
    ("student_id", re.compile(r"(?:学号|工号|student\s*id)\s*[:：#]?\s*[A-Za-z0-9-]{5,}", re.I)),
    ("personal_name", re.compile(r"(?:姓名|联系人|name)\s*[:：]\s*[\u4e00-\u9fffA-Za-z· ]{2,30}", re.I)),
    ("qr_content", re.compile(r"(?:二维码(?:内容)?|qr(?:code)?(?:\s*content)?)\s*[:：]\s*\S+", re.I)),
    ("personal_path", re.compile(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+")),
)


def find_sensitive_text(value: Any, *, field: str = "value") -> list[PrivacyFinding]:
    """Return finding categories only; never echo the sensitive value."""
    text = "" if value is None else str(value)
    return [PrivacyFinding(kind, field) for kind, pattern in _PATTERNS if pattern.search(text)]


def redact_sensitive_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    for _, pattern in _PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def assert_public_payload_safe(payload: Any, *, field: str = "payload") -> None:
    findings: list[PrivacyFinding] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            findings.extend(_walk(value, f"{field}.{key}"))
    else:
        findings.extend(_walk(payload, field))
    if findings:
        locations = ", ".join(sorted({f"{item.kind}@{item.field}" for item in findings}))
        raise ValueError(f"Public output contains prohibited privacy patterns: {locations}")


def _walk(value: Any, field: str) -> list[PrivacyFinding]:
    if isinstance(value, dict):
        return [item for key, child in value.items() for item in _walk(child, f"{field}.{key}")]
    if isinstance(value, (list, tuple)):
        return [item for index, child in enumerate(value) for item in _walk(child, f"{field}[{index}]")]
    return find_sensitive_text(value, field=field)
