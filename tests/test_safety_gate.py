from datetime import datetime

import pytest

from glanceflow.domain.enums import NoticeType, SafetyGateStatus
from glanceflow.domain.models import NoticePackageDraft
from glanceflow.safety.gate import evaluate_notice


def failed_rule_ids(decision):
    return {result.rule_id for result in decision.rule_results if not result.passed}


def test_valid_plain_event(draft_factory):
    draft = draft_factory()
    before = draft.model_dump_json()
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.READY_TO_CONFIRM
    assert decision.can_proceed_to_confirmation is True
    assert failed_rule_ids(decision) == set()
    assert len(decision.rule_results) == 16
    assert draft.model_dump_json() == before


def test_valid_event_with_deadline(draft_factory):
    decision = evaluate_notice(draft_factory(with_deadline=True))
    assert decision.status is SafetyGateStatus.READY_TO_CONFIRM
    assert "GF-DEADLINE-001" not in failed_rule_ids(decision)
    assert "GF-DEADLINE-002" not in failed_rule_ids(decision)


def test_missing_location_needs_input(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.location = ""
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    assert "GF-FIELD-002" in failed_rule_ids(decision)


@pytest.mark.parametrize(
    ("weekday", "expected_status"),
    [("星期五", SafetyGateStatus.READY_TO_CONFIRM), ("星期四", SafetyGateStatus.CONTRADICTION_BLOCKED)],
)
def test_date_weekday_consistency(draft_factory, weekday, expected_status):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.raw_weekday_text = weekday
    decision = evaluate_notice(draft)
    assert decision.status is expected_status
    assert ("GF-TIME-004" in failed_rule_ids(decision)) is (weekday == "星期四")


def test_unresolved_time_needs_input(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.unresolved_time_expression = "周五下午"
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    assert "GF-TIME-005" in failed_rule_ids(decision)


def test_expired_event_blocked(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.event_start = datetime.fromisoformat("2026-07-31T14:00:00+08:00")
    draft.main_event.raw_date_text = None
    draft.main_event.raw_weekday_text = None
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-TIME-003" in failed_rule_ids(decision)


def test_defensive_timezone_rules(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.captured_at = datetime(2026, 8, 1, 9, 0)
    draft.main_event.event_start = datetime(2026, 8, 7, 14, 0)
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert {"GF-TIME-001", "GF-TIME-002", "GF-TIME-003"} <= failed_rule_ids(decision)


def test_missing_deadline_action(draft_factory):
    draft = draft_factory(with_deadline=True).model_copy(deep=True)
    draft.deadline_action.action = ""
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    assert "GF-DEADLINE-001" in failed_rule_ids(decision)


def test_invalid_deadline_time(draft_factory):
    draft = draft_factory(with_deadline=True).model_copy(deep=True)
    draft.deadline_action.deadline = datetime.fromisoformat("2026-08-08T20:00:00+08:00")
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-DEADLINE-002" in failed_rule_ids(decision)


def test_missing_evidence(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.location_evidence.evidence_line_ids = []
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    assert "GF-EVIDENCE-001" in failed_rule_ids(decision)


def test_invalid_line_id_requires_recapture(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.time_evidence.evidence_line_ids = ["ocr-missing"]
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.RECAPTURE_REQUIRED
    assert "GF-EVIDENCE-002" in failed_rule_ids(decision)


def test_evidence_source_mismatch_requires_recapture(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.evidence_lines[0].source_frame_id = "frame-other"
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.RECAPTURE_REQUIRED
    assert "GF-EVIDENCE-003" in failed_rule_ids(decision)


def test_low_confidence_requires_recapture(draft_factory):
    draft = draft_factory().model_copy(deep=True)
    draft.evidence_lines[1].confidence = 0.70
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.RECAPTURE_REQUIRED
    assert "GF-CONFIDENCE-001" in failed_rule_ids(decision)


def test_notice_type_contradiction(draft_factory):
    draft = draft_factory(with_deadline=True).model_copy(deep=True)
    draft.notice_type = NoticeType.EVENT_NOTICE
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-NOTICE-001" in failed_rule_ids(decision)


def test_duplicate_notice(draft_factory):
    existing = draft_factory()
    duplicate = existing.model_copy(deep=True)
    duplicate.notice_package_id = "GF-PKG-0009"
    duplicate.main_event.title = "创新创业竞赛 宣讲"
    decision = evaluate_notice(duplicate, [existing])
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-DUPLICATE-001" in failed_rule_ids(decision)


def test_all_four_statuses(draft_factory):
    ready = draft_factory()
    need = draft_factory().model_copy(deep=True)
    need.main_event.location = ""
    recapture = draft_factory().model_copy(deep=True)
    recapture.main_event.time_evidence.confidence = 0.5
    blocked = draft_factory().model_copy(deep=True)
    blocked.main_event.event_start = blocked.captured_at
    blocked.main_event.raw_date_text = None
    blocked.main_event.raw_weekday_text = None

    statuses = {evaluate_notice(item).status for item in [ready, need, recapture, blocked]}
    assert statuses == set(SafetyGateStatus)


@pytest.mark.parametrize(
    ("with_block", "expected"),
    [(False, SafetyGateStatus.RECAPTURE_REQUIRED), (True, SafetyGateStatus.CONTRADICTION_BLOCKED)],
)
def test_status_priority(draft_factory, with_block, expected):
    draft = draft_factory().model_copy(deep=True)
    draft.main_event.location = ""
    draft.main_event.title_evidence.confidence = 0.5
    if with_block:
        draft.main_event.event_start = draft.captured_at
        draft.main_event.raw_date_text = None
        draft.main_event.raw_weekday_text = None
    decision = evaluate_notice(draft)
    assert decision.status is expected
    assert "GF-FIELD-002" in failed_rule_ids(decision)
    assert "GF-CONFIDENCE-001" in failed_rule_ids(decision)
    if with_block:
        assert "GF-TIME-003" in failed_rule_ids(decision)
