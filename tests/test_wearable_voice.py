from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from glanceflow.wearable.models import VoiceIntent
from glanceflow.wearable.voice import interpret_voice


NOW = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


@pytest.mark.parametrize(
    ("text", "intent"),
    [("帮我安排", VoiceIntent.ARRANGE), ("确认。", VoiceIntent.CONFIRM), ("算了", VoiceIntent.CANCEL), ("撤销上一步", VoiceIntent.UNDO_LAST)],
)
def test_voice_whitelist(text, intent):
    result = interpret_voice(text, confidence=0.99, captured_at=NOW, source="test", session_id="s1")
    assert result.intent is intent
    assert result.raw_text == text


def test_unknown_and_low_confidence_do_nothing():
    unknown = interpret_voice("帮我报名", confidence=0.99, captured_at=NOW, source="test", session_id="s1")
    low = interpret_voice("确认", confidence=0.3, captured_at=NOW, source="test", session_id="s1")
    assert unknown.intent is VoiceIntent.UNKNOWN
    assert low.intent is VoiceIntent.UNKNOWN
