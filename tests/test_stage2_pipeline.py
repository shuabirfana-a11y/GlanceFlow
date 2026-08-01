from datetime import datetime
from pathlib import Path
import shutil

import pytest

from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.pipeline import process_image


ROOT = Path(__file__).resolve().parents[1]
POSTERS = ROOT / "data" / "synthetic_posters"
CAPTURED_AT = datetime.fromisoformat("2026-08-01T09:00:00+08:00")


@pytest.fixture(scope="module")
def image_results():
    provider = RapidOcrProvider()
    return {
        path.name: process_image(path, CAPTURED_AT, provider=provider)
        for path in sorted(POSTERS.glob("*.png"))
    }


def failed_rule_ids(result):
    if result.safety_decision is None:
        return set()
    return {rule.rule_id for rule in result.safety_decision.rule_results if not rule.passed}


def test_all_ten_images_processed(image_results):
    assert len(image_results) == 10
    assert all(result.image_path.is_file() for result in image_results.values())


def test_clear_event_ready_with_real_fields_and_evidence(image_results):
    result = image_results["01_valid_event.png"]
    assert result.final_status is SafetyGateStatus.READY_TO_CONFIRM
    assert result.extraction_result is not None and result.extraction_result.draft is not None
    draft = result.extraction_result.draft
    assert draft.main_event.title == "创新创业竞赛宣讲"
    assert draft.main_event.event_start.isoformat() == "2026-08-07T14:00:00+08:00"
    assert draft.main_event.location == "科技馆报告厅"
    assert draft.main_event.raw_weekday_text == "星期五"
    assert draft.main_event.title_evidence.evidence_line_ids == ["frame-01_valid_event-ocr-0002"]


def test_event_with_deadline_ready_and_semantically_separated(image_results):
    result = image_results["02_event_with_deadline.png"]
    assert result.final_status is SafetyGateStatus.READY_TO_CONFIRM
    draft = result.extraction_result.draft
    assert draft is not None and draft.deadline_action is not None
    assert draft.main_event.event_start.isoformat() == "2026-08-08T15:00:00+08:00"
    assert draft.deadline_action.deadline.isoformat() == "2026-08-07T20:00:00+08:00"
    assert draft.deadline_action.action == "完成实验室报名"
    assert draft.main_event.time_evidence.evidence_line_ids != draft.deadline_action.deadline_evidence.evidence_line_ids


@pytest.mark.parametrize(
    ("filename", "status", "rule_id"),
    [
        ("03_weekday_contradiction.png", SafetyGateStatus.CONTRADICTION_BLOCKED, "GF-TIME-004"),
        ("05_missing_location.png", SafetyGateStatus.NEED_USER_INPUT, "GF-FIELD-002"),
        ("06_expired_event.png", SafetyGateStatus.CONTRADICTION_BLOCKED, "GF-TIME-003"),
        ("07_deadline_after_event.png", SafetyGateStatus.CONTRADICTION_BLOCKED, "GF-DEADLINE-002"),
    ],
)
def test_image_safety_gate_rules(image_results, filename, status, rule_id):
    result = image_results[filename]
    assert result.final_status is status
    assert rule_id in failed_rule_ids(result)


def test_unresolved_time_needs_input_without_guessed_draft(image_results):
    result = image_results["04_unresolved_time.png"]
    assert result.final_status is SafetyGateStatus.NEED_USER_INPUT
    assert result.extraction_result is not None
    assert result.extraction_result.draft is None
    assert result.extraction_result.issues[0].issue_id == "GF-EXTRACT-TIME-MISSING"
    assert "周五下午" in result.extraction_result.issues[0].message


@pytest.mark.parametrize(
    ("filename", "check_id"),
    [
        ("08_low_resolution.png", "GF-IMG-RESOLUTION"),
        ("09_blurred_image.png", "GF-IMG-SHARPNESS"),
    ],
)
def test_bad_image_requires_recapture_before_ocr(image_results, filename, check_id):
    result = image_results[filename]
    assert result.final_status is SafetyGateStatus.RECAPTURE_REQUIRED
    assert result.ocr_result is None
    assert check_id in {check.check_id for check in result.quality_result.checks if not check.passed}


def test_ambiguous_times_are_preserved_and_blocked(image_results):
    result = image_results["10_ambiguous_times.png"]
    assert result.final_status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert result.extraction_result is not None
    assert result.extraction_result.draft is None
    issue = result.extraction_result.issues[0]
    assert issue.issue_id == "GF-EXTRACT-TIME-AMBIGUOUS"
    assert len(issue.evidence_line_ids) == 2


def test_real_ocr_lines_have_unique_ids_valid_bbox_and_source(image_results):
    for result in image_results.values():
        if result.ocr_result is None:
            continue
        ocr = result.ocr_result
        ids = [line.line_id for line in ocr.evidence_lines]
        assert len(ids) == len(set(ids))
        for line in ocr.evidence_lines:
            assert line.source_frame_id == result.source_frame_id
            assert line.bbox is not None
            x1, y1, x2, y2 = line.bbox
            assert 0 <= x1 <= x2 <= ocr.image_width
            assert 0 <= y1 <= y2 <= ocr.image_height


def test_extracted_fields_cannot_reference_non_ocr_lines(image_results):
    for result in image_results.values():
        if not result.extraction_result or not result.extraction_result.draft or not result.ocr_result:
            continue
        draft = result.extraction_result.draft
        known = {line.line_id for line in result.ocr_result.evidence_lines}
        bindings = [
            draft.main_event.title_evidence,
            draft.main_event.time_evidence,
            draft.main_event.location_evidence,
        ]
        if draft.deadline_action:
            bindings.extend([draft.deadline_action.deadline_evidence, draft.deadline_action.action_evidence])
        assert all(set(binding.evidence_line_ids) <= known for binding in bindings)


def test_real_ocr_supports_chinese_windows_path(tmp_path):
    chinese_path = tmp_path / "校园通知图片.png"
    shutil.copyfile(POSTERS / "01_valid_event.png", chinese_path)
    result = process_image(chinese_path, CAPTURED_AT, provider=RapidOcrProvider())
    assert result.ocr_result is not None and result.ocr_result.success is True
    assert result.source_frame_id == "frame-校园通知图片"
    assert result.final_status is SafetyGateStatus.READY_TO_CONFIRM
    assert result.extraction_result.draft.main_event.title == "创新创业竞赛宣讲"
