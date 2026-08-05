from copy import deepcopy

import pytest

from glanceflow.domain.models import NoticePackageDraft
from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.calendar.models import EventRole, UserConfirmation, calendar_request_digest
from glanceflow.safety.gate import evaluate_notice


def base_payload(*, with_deadline: bool = False) -> dict:
    payload = {
        "notice_package_id": "GF-PKG-0001",
        "notice_type": "EVENT_WITH_DEADLINE" if with_deadline else "EVENT_NOTICE",
        "captured_at": "2026-08-01T09:00:00+08:00",
        "timezone": "Asia/Shanghai",
        "source_frame_id": "frame-001",
        "main_event": {
            "title": "创新创业竞赛宣讲",
            "event_start": "2026-08-07T14:00:00+08:00",
            "location": "科技馆报告厅",
            "title_evidence": {"evidence_line_ids": ["ocr-01"], "confidence": 0.98},
            "time_evidence": {"evidence_line_ids": ["ocr-02"], "confidence": 0.97},
            "location_evidence": {"evidence_line_ids": ["ocr-03"], "confidence": 0.96},
            "raw_date_text": "2026年8月7日",
            "raw_weekday_text": "星期五",
            "unresolved_time_expression": None,
        },
        "deadline_action": None,
        "evidence_lines": [
            {"line_id": "ocr-01", "text": "创新创业竞赛宣讲", "confidence": 0.98, "source_frame_id": "frame-001", "bbox": [10, 10, 300, 40]},
            {"line_id": "ocr-02", "text": "2026年8月7日 星期五 14:00", "confidence": 0.97, "source_frame_id": "frame-001", "bbox": [10, 50, 350, 80]},
            {"line_id": "ocr-03", "text": "地点：科技馆报告厅", "confidence": 0.96, "source_frame_id": "frame-001", "bbox": [10, 90, 320, 120]},
        ],
        "extraction_version": "stage1-manual-v1",
        "metadata": {"scenario": "valid_event"},
    }
    if with_deadline:
        payload["deadline_action"] = {
            "deadline": "2026-08-06T20:00:00+08:00",
            "action": "完成竞赛报名",
            "role": "REGISTRATION",
            "deadline_evidence": {"evidence_line_ids": ["ocr-04"], "confidence": 0.95},
            "action_evidence": {"evidence_line_ids": ["ocr-05"], "confidence": 0.94},
        }
        payload["evidence_lines"].extend(
            [
                {"line_id": "ocr-04", "text": "报名截止：8月6日20:00", "confidence": 0.95, "source_frame_id": "frame-001", "bbox": [10, 130, 330, 160]},
                {"line_id": "ocr-05", "text": "请完成竞赛报名", "confidence": 0.94, "source_frame_id": "frame-001", "bbox": [10, 170, 300, 200]},
            ]
        )
    return payload


@pytest.fixture
def payload_factory():
    def factory(*, with_deadline: bool = False) -> dict:
        return deepcopy(base_payload(with_deadline=with_deadline))

    return factory


@pytest.fixture
def draft_factory(payload_factory):
    def factory(*, with_deadline: bool = False) -> NoticePackageDraft:
        return NoticePackageDraft.model_validate(payload_factory(with_deadline=with_deadline))

    return factory


@pytest.fixture
def scheduling_factory(draft_factory):
    def factory(*, with_deadline=False, provider=None, transaction_id="GF-TX-TEST-0001"):
        draft = draft_factory(with_deadline=with_deadline)
        decision = evaluate_notice(draft)
        calendar = provider or MemoryCalendarProvider()
        service = TrustedSchedulingService(calendar)
        preflight = service.preflight(draft, decision, transaction_id=transaction_id)
        return service, calendar, draft, decision, preflight

    return factory


@pytest.fixture
def confirmation_factory():
    def factory(record, *, confirmed=True, accepted_conflict=False, **changes):
        main = next(request for request in record.planned_requests if request.event_role is EventRole.MAIN_EVENT)
        deadline = next(
            (request for request in record.planned_requests if request.event_role is EventRole.DEADLINE_EVENT),
            None,
        )
        data = {
            "confirmed": confirmed,
            "confirmed_at": "2026-08-01T09:01:00+08:00",
            "confirmed_title": main.title,
            "confirmed_event_start": main.start_time,
            "confirmed_location": main.location,
            "confirmed_deadline": deadline.start_time if deadline else None,
            "confirmed_calendar_id": record.calendar_id,
            "confirmed_request_hash": calendar_request_digest(record.planned_requests),
            "accepted_conflict": accepted_conflict,
            "confirmation_source": "pytest-structured-confirmation",
        }
        data.update(changes)
        return UserConfirmation.model_validate(data)

    return factory
