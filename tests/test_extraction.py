from datetime import datetime
from pathlib import Path

from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.domain.models import EvidenceLine
from glanceflow.extraction.extractor import DeterministicDraftExtractor
from glanceflow.extraction.schemas import ExtractionResult
from glanceflow.ocr.models import OcrResult
from glanceflow.pipeline import process_image
from glanceflow.safety.gate import evaluate_notice


CAPTURED_AT = datetime.fromisoformat("2026-08-01T09:00:00+08:00")


def make_ocr(rows: list[list[tuple[str, float]]], source="frame-01-valid") -> OcrResult:
    lines = []
    index = 0
    for row_index, row in enumerate(rows):
        x = 40.0
        y = 50.0 + row_index * 90
        for text, confidence in row:
            index += 1
            width = max(80.0, len(text) * 35.0)
            lines.append(
                EvidenceLine(
                    line_id=f"{source}-ocr-{index:04d}",
                    text=text,
                    confidence=confidence,
                    source_frame_id=source,
                    bbox=(x, y, x + width, y + 48),
                )
            )
            x += width + 12
    return OcrResult(
        source_frame_id=source,
        image_path=Path("synthetic.png"),
        image_width=1400,
        image_height=900,
        image_sha256="0" * 64,
        evidence_lines=lines,
        provider_name="fake-ocr",
        provider_version="1",
        processing_time_ms=1.0,
        success=True,
    )


def valid_rows():
    return [
        [("活动标题：创新创业竞赛宣讲", 0.98)],
        [("2026年8月7日", 0.97), ("星期五", 0.96), ("14:00", 0.95)],
        [("地点：科技馆报告厅", 0.96)],
    ]


def test_title_time_location_and_weekday_extraction():
    ocr = make_ocr(valid_rows())
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.success is True
    assert result.draft is not None
    assert result.draft.main_event.title == "创新创业竞赛宣讲"
    assert result.draft.main_event.event_start.isoformat() == "2026-08-07T14:00:00+08:00"
    assert result.draft.main_event.location == "科技馆报告厅"
    assert result.draft.main_event.raw_weekday_text == "星期五"
    assert result.draft.main_event.title_evidence.evidence_line_ids == ["frame-01-valid-ocr-0001"]
    assert result.draft.main_event.time_evidence.evidence_line_ids == [
        "frame-01-valid-ocr-0002",
        "frame-01-valid-ocr-0003",
        "frame-01-valid-ocr-0004",
    ]


def test_deadline_is_distinguished_from_event_time_and_action_extracted():
    rows = valid_rows() + [
        [("报名截止：2026年8月6日 20:00", 0.94)],
        [("截止动作：完成竞赛报名", 0.93)],
    ]
    ocr = make_ocr(rows, source="frame-02-deadline")
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.success is True
    assert result.draft is not None
    assert result.draft.main_event.event_start.isoformat() == "2026-08-07T14:00:00+08:00"
    assert result.draft.deadline_action is not None
    assert result.draft.deadline_action.deadline.isoformat() == "2026-08-06T20:00:00+08:00"
    assert result.draft.deadline_action.action == "完成竞赛报名"
    assert result.draft.deadline_action.deadline_evidence.evidence_line_ids == ["frame-02-deadline-ocr-0006"]
    assert result.draft.deadline_action.action_evidence.evidence_line_ids == ["frame-02-deadline-ocr-0007"]


def test_relative_time_is_not_guessed():
    ocr = make_ocr(
        [
            [("活动标题：摄影社交流活动", 0.98)],
            [("周五下午", 0.96)],
            [("地点：大学生活动中心", 0.95)],
        ],
        source="frame-04-relative",
    )
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.success is False
    assert result.draft is None
    assert result.suggested_status is SafetyGateStatus.NEED_USER_INPUT
    assert result.issues[0].issue_id == "GF-EXTRACT-TIME-MISSING"
    assert "周五" in result.issues[0].message


def test_multiple_event_times_are_blocked_and_preserved():
    rows = valid_rows() + [[("2026年8月8日 星期六 15:00", 0.94)]]
    result = DeterministicDraftExtractor().extract(
        make_ocr(rows, source="frame-10-ambiguous"), CAPTURED_AT, "Asia/Shanghai"
    )
    assert result.success is False
    assert result.suggested_status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert result.issues[0].issue_id == "GF-EXTRACT-TIME-AMBIGUOUS"
    assert len(result.issues[0].evidence_line_ids) == 4


def test_all_field_links_exist_in_ocr_result():
    ocr = make_ocr(valid_rows())
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.draft is not None
    known = {line.line_id for line in ocr.evidence_lines}
    event = result.draft.main_event
    linked = (
        event.title_evidence.evidence_line_ids
        + event.time_evidence.evidence_line_ids
        + event.location_evidence.evidence_line_ids
    )
    assert linked
    assert set(linked) <= known


def test_missing_location_remains_user_input_not_low_confidence():
    rows = valid_rows()[:2]
    result = DeterministicDraftExtractor().extract(
        make_ocr(rows, source="frame-05-no-location"), CAPTURED_AT, "Asia/Shanghai"
    )
    assert result.draft is not None
    decision = evaluate_notice(result.draft)
    failures = {rule.rule_id for rule in decision.rule_results if not rule.passed}
    assert decision.status is SafetyGateStatus.NEED_USER_INPUT
    assert {"GF-FIELD-002", "GF-EVIDENCE-001"} <= failures
    assert "GF-CONFIDENCE-001" not in failures


def test_forged_line_id_is_stopped_by_existing_safety_gate(tmp_path):
    from PIL import Image, ImageDraw

    image_path = tmp_path / "clear.png"
    image = Image.new("RGB", (1200, 700), "white")
    ImageDraw.Draw(image).rectangle((80, 80, 1100, 620), outline="black", width=8)
    image.save(image_path)
    ocr = make_ocr(valid_rows(), source="frame-clear")

    class StaticProvider:
        def recognize(self, _image_path, source_frame_id):
            return ocr.model_copy(update={"source_frame_id": source_frame_id})

    class ForgingExtractor:
        def extract(self, ocr_result, captured_at, timezone):
            legitimate = DeterministicDraftExtractor().extract(ocr, captured_at, timezone)
            draft = legitimate.draft.model_copy(deep=True)
            draft.source_frame_id = ocr_result.source_frame_id
            draft.main_event.title_evidence.evidence_line_ids = ["forged-line-id"]
            return ExtractionResult(success=True, draft=draft)

    result = process_image(
        image_path,
        CAPTURED_AT,
        provider=StaticProvider(),
        extractor=ForgingExtractor(),
    )
    assert result.final_status is SafetyGateStatus.RECAPTURE_REQUIRED
    assert result.safety_decision is not None
    failures = {rule.rule_id for rule in result.safety_decision.rule_results if not rule.passed}
    assert "GF-EVIDENCE-002" in failures
