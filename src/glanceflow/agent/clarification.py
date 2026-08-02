from __future__ import annotations

from dataclasses import dataclass


PRIORITY = ("event_start", "location", "time_role", "conflict_acceptance")
QUESTIONS = {
    "event_start": "活动的具体日期和时间是什么？",
    "location": "活动地点在哪里？",
    "time_role": "这个时间是活动开始时间，还是报名截止时间？",
    "conflict_acceptance": "该时段与现有日程冲突，是否仍然创建？请明确说“仍然创建”。",
}


@dataclass(frozen=True)
class ClarificationRequest:
    field: str | None
    question: str | None
    exhausted: bool
    request_recapture: bool = False


class ClarificationPolicy:
    max_rounds_per_field = 2

    def choose(self, unresolved: list[str], counts: dict[str, int], risks: list[str]) -> ClarificationRequest:
        if any(item in risks for item in ("poor_image_quality", "low_ocr_confidence", "insufficient_evidence")):
            return ClarificationRequest(None, "画面证据不足，请重新采集通知。", False, True)
        ordered = [field for field in PRIORITY if field in unresolved]
        ordered.extend(field for field in unresolved if field not in ordered)
        for field in ordered:
            if counts.get(field, 0) < self.max_rounds_per_field:
                return ClarificationRequest(field, QUESTIONS.get(field, f"请补充{field}。"), False)
        return ClarificationRequest(None, None, bool(unresolved))
