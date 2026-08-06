from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from glanceflow.domain.enums import TemporalNormalizationStatus, TemporalType
from glanceflow.domain.models import TemporalEvidenceBinding, TemporalField
from glanceflow.extraction.evidence_linker import EvidenceRow


SAFETY_GATE_RULE_VERSION = "safety-gate-v1"

_TIME = re.compile(
    r"(?<!\d)(?P<hour>[01]?\d|2[0-3])(?:\s*[:：点时]\s*)(?P<minute>[0-5]\d)(?:\s*分)?(?!\d)"
)
_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def classify_temporal_type(text: str) -> TemporalType:
    normalized = text.casefold()
    if any(word in normalized for word in ("取消", "撤销", "作废")):
        return TemporalType.CANCELLATION_TIME
    if any(word in normalized for word in ("延期至", "改为", "调整至", "变更为", "顺延至")):
        return TemporalType.RESCHEDULED_TIME
    if any(word in normalized for word in ("发布时间", "发布于", "发布日期", "公告时间")):
        return TemporalType.PUBLICATION_TIME
    if any(word in normalized for word in ("报名截止", "注册截止")):
        return TemporalType.REGISTRATION_DEADLINE
    if any(word in normalized for word in ("提交截止", "申请截止", "材料截止", "投稿截止")):
        return TemporalType.SUBMISSION_DEADLINE
    if any(word in normalized for word in ("签到", "报到", "入场", "检录")):
        return TemporalType.CHECK_IN_TIME
    if any(word in normalized for word in ("结束时间", "活动结束", "结束于")):
        return TemporalType.EVENT_END
    if any(word in normalized for word in ("其他时间", "相关时间", "未知时间字段")):
        return TemporalType.UNKNOWN_TEMPORAL_FIELD
    return TemporalType.EVENT_START


def normalize_relative_datetime(
    text: str, reference_time: datetime, timezone: str
) -> tuple[datetime | None, str | None]:
    """Resolve only bounded relative expressions against capture time in the user timezone."""
    local_reference = reference_time.astimezone(ZoneInfo(timezone))
    time_match = _TIME.search(text)
    if time_match is None:
        return None, None
    hour = int(time_match.group("hour"))
    minute = int(time_match.group("minute"))

    if "明天" in text:
        target_date = local_reference.date() + timedelta(days=1)
    elif "后天" in text:
        target_date = local_reference.date() + timedelta(days=2)
    elif "今天" in text:
        target_date = local_reference.date()
    else:
        weekday = re.search(r"本周([一二三四五六日天])", text)
        if weekday is None:
            return None, None
        delta = _WEEKDAYS[weekday.group(1)] - local_reference.weekday()
        if delta < 0:
            return None, None
        target_date = local_reference.date() + timedelta(days=delta)

    value = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        hour,
        minute,
        tzinfo=ZoneInfo(timezone),
    )
    return value, time_match.group(0)


def image_sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_temporal_field(
    *,
    row: EvidenceRow,
    value: datetime | None,
    temporal_type: TemporalType,
    timezone: str,
    relative_reference_time: datetime | None,
    image_hash: str | None,
    ocr_version: str,
    extraction_rule_version: str,
    normalization_status: TemporalNormalizationStatus | None = None,
) -> TemporalField:
    status = normalization_status or (
        TemporalNormalizationStatus.NORMALIZED
        if value is not None and image_hash is not None
        else (
            TemporalNormalizationStatus.EVIDENCE_INCOMPLETE
            if value is not None
            else TemporalNormalizationStatus.UNRESOLVED
        )
    )
    normalized_value = value.isoformat() if value is not None else None
    binding = TemporalEvidenceBinding(
        image_sha256=image_hash,
        source_frame_id=row.lines[0].source_frame_id,
        evidence_line_ids=row.line_ids,
        bbox=row.bbox,
        ocr_text=row.text,
        normalized_value=normalized_value,
        ocr_confidence=row.confidence,
        ocr_version=ocr_version,
        extraction_rule_version=extraction_rule_version,
        safety_gate_rule_version=SAFETY_GATE_RULE_VERSION,
    )
    identity = {
        "temporal_type": temporal_type.value,
        "timezone": timezone,
        "source_text": row.text,
        "relative_reference_time": (
            relative_reference_time.isoformat() if relative_reference_time is not None else None
        ),
        "evidence": binding.model_dump(mode="json"),
    }
    evidence_id = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return TemporalField(
        value=value,
        temporal_type=temporal_type,
        timezone=timezone,
        source_text=row.text,
        confidence=row.confidence,
        evidence_id=evidence_id,
        relative_reference_time=relative_reference_time,
        normalization_status=status,
        evidence=binding,
    )
