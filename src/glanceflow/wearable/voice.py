from __future__ import annotations

import re
from datetime import datetime

from glanceflow.wearable.models import VoiceIntent, VoiceTriggerEvent


_PHRASES: dict[VoiceIntent, set[str]] = {
    VoiceIntent.ARRANGE: {"帮我安排", "安排一下", "加入日程", "创建日程"},
    VoiceIntent.CONFIRM: {"确认", "确定", "确认创建", "同意"},
    VoiceIntent.CANCEL: {"取消", "算了", "不要了", "停止"},
    VoiceIntent.UNDO_LAST: {"撤销上一步", "撤销", "删除刚才日程", "取消刚才安排"},
}


def normalize_voice_text(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?]+", "", text).lower()


def interpret_voice(
    raw_text: str,
    *,
    confidence: float,
    captured_at: datetime,
    source: str,
    session_id: str,
    minimum_confidence: float = 0.72,
) -> VoiceTriggerEvent:
    normalized = normalize_voice_text(raw_text)
    intent = VoiceIntent.UNKNOWN
    if confidence >= minimum_confidence:
        for candidate, phrases in _PHRASES.items():
            if normalized in phrases:
                intent = candidate
                break
    return VoiceTriggerEvent(
        raw_text=raw_text,
        normalized_text=normalized,
        intent=intent,
        confidence=confidence,
        captured_at=captured_at,
        source=source,
        session_id=session_id,
    )
