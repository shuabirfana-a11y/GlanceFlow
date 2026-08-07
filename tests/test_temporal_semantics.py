import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from glanceflow.application.scheduling_service import (
    SchedulingValidationError,
    TrustedSchedulingService,
)
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.domain.enums import (
    SafetyGateStatus,
    TemporalNormalizationStatus,
    TemporalType,
)
from glanceflow.domain.models import NoticePackageDraft, TemporalField
from glanceflow.extraction.extractor import DeterministicDraftExtractor
from glanceflow.extraction.temporal import (
    classify_temporal_type,
    normalize_relative_datetime,
)
from glanceflow.safety.gate import evaluate_notice
from tests.test_extraction import CAPTURED_AT, make_ocr, valid_rows


def _extract(rows, *, source="frame-temporal", captured_at=CAPTURED_AT):
    return DeterministicDraftExtractor().extract(
        make_ocr(rows, source=source), captured_at, "Asia/Shanghai"
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("活动时间", TemporalType.EVENT_START),
        ("活动结束时间", TemporalType.EVENT_END),
        ("报名截止", TemporalType.REGISTRATION_DEADLINE),
        ("材料提交截止", TemporalType.SUBMISSION_DEADLINE),
        ("签到时间", TemporalType.CHECK_IN_TIME),
        ("公告发布时间", TemporalType.PUBLICATION_TIME),
        ("活动取消", TemporalType.CANCELLATION_TIME),
        ("延期至", TemporalType.RESCHEDULED_TIME),
        ("其他时间", TemporalType.UNKNOWN_TEMPORAL_FIELD),
    ],
)
def test_all_required_temporal_types_are_distinguished(text, expected):
    assert classify_temporal_type(text) is expected


def test_relative_time_uses_capture_time_and_user_timezone():
    captured_at = datetime(2026, 8, 1, 16, 30, tzinfo=timezone.utc)
    result = _extract(
        [
            [("活动标题：摄影社交流活动", 0.98)],
            [("活动时间：明天 14:30", 0.96)],
            [("地点：大学生活动中心", 0.95)],
        ],
        source="frame-relative-resolved",
        captured_at=captured_at,
    )
    assert result.success is True
    assert result.draft is not None
    assert result.draft.main_event.event_start.isoformat() == "2026-08-03T14:30:00+08:00"
    field = result.draft.temporal_fields[0]
    assert field.relative_reference_time == captured_at
    assert field.timezone == "Asia/Shanghai"
    assert field.normalization_status is TemporalNormalizationStatus.NORMALIZED


def test_publication_and_event_end_are_not_misclassified_as_event_start():
    rows = [
        [("活动标题：创新论坛", 0.98)],
        [("公告发布时间：2026年8月1日 08:00", 0.97)],
        [("活动时间：2026年8月7日 14:00", 0.96)],
        [("活动结束时间：2026年8月7日 16:00", 0.95)],
        [("地点：科技馆", 0.95)],
    ]
    result = _extract(rows, source="frame-publication")
    assert result.success is True and result.draft is not None
    assert result.draft.main_event.event_start.isoformat() == "2026-08-07T14:00:00+08:00"
    assert {item.temporal_type for item in result.draft.temporal_fields} == {
        TemporalType.PUBLICATION_TIME,
        TemporalType.EVENT_START,
        TemporalType.EVENT_END,
    }


def test_rescheduled_time_supersedes_original_without_erasing_evidence():
    rows = [
        [("活动标题：创新论坛", 0.98)],
        [("原定：2026年8月7日 14:00", 0.97)],
        [("延期至：2026年8月8日 15:00", 0.96)],
        [("地点：科技馆", 0.95)],
    ]
    result = _extract(rows, source="frame-rescheduled")
    assert result.success is True and result.draft is not None
    assert result.draft.main_event.event_start.isoformat() == "2026-08-08T15:00:00+08:00"
    assert [item.temporal_type for item in result.draft.temporal_fields] == [
        TemporalType.EVENT_START,
        TemporalType.RESCHEDULED_TIME,
    ]


def test_original_and_rescheduled_times_on_one_ocr_row_are_both_preserved():
    rows = [
        [("活动标题：创新论坛", 0.98)],
        [("原定 2026年8月7日 14:00，延期至 2026年8月8日 15:00", 0.97)],
        [("地点：科技馆", 0.95)],
    ]
    result = _extract(rows, source="frame-one-row-reschedule")
    assert result.success is True and result.draft is not None
    assert result.draft.main_event.event_start.isoformat() == "2026-08-08T15:00:00+08:00"
    assert [item.temporal_type for item in result.draft.temporal_fields] == [
        TemporalType.EVENT_START,
        TemporalType.RESCHEDULED_TIME,
    ]
    assert len({item.evidence_id for item in result.draft.temporal_fields}) == 2


def test_cancellation_blocks_even_without_a_cancellation_timestamp():
    result = _extract(valid_rows() + [[("本活动已取消", 0.99)]], source="frame-cancelled")
    assert result.success is False
    assert result.suggested_status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert result.issues[0].issue_id == "GF-EXTRACT-EVENT-CANCELLED"
    cancellation = next(
        item for item in result.temporal_fields if item.temporal_type is TemporalType.CANCELLATION_TIME
    )
    assert cancellation.value is None
    assert cancellation.normalization_status is TemporalNormalizationStatus.CANCELLED


def test_same_role_conflict_preserves_each_candidate_as_conflicting():
    result = _extract(
        valid_rows() + [[("活动时间：2026年8月8日 15:00", 0.94)]],
        source="frame-semantic-conflict",
    )
    assert result.success is False
    assert result.issues[0].issue_id == "GF-EXTRACT-TIME-AMBIGUOUS"
    assert len(result.temporal_fields) == 2
    assert all(
        item.normalization_status is TemporalNormalizationStatus.CONFLICTING
        for item in result.temporal_fields
    )


@pytest.mark.parametrize(
    "label,expected_type",
    [
        ("报名截止", TemporalType.REGISTRATION_DEADLINE),
        ("材料提交截止", TemporalType.SUBMISSION_DEADLINE),
    ],
)
def test_deadline_role_is_separate_from_event_start(label, expected_type):
    rows = valid_rows() + [
        [(f"{label}：2026年8月6日 20:00", 0.94)],
        [("截止动作：完成材料", 0.93)],
    ]
    result = _extract(rows, source=f"frame-{expected_type.value.lower()}")
    assert result.success is True and result.draft is not None
    deadline = next(item for item in result.draft.temporal_fields if item.temporal_type is expected_type)
    event = next(
        item for item in result.draft.temporal_fields if item.temporal_type is TemporalType.EVENT_START
    )
    assert deadline.value != event.value
    assert deadline.evidence_id != event.evidence_id


def test_check_in_time_is_recorded_but_not_turned_into_a_deadline_event():
    rows = valid_rows() + [[("签到时间：2026年8月7日 13:30", 0.94)]]
    result = _extract(rows, source="frame-check-in")
    assert result.success is True and result.draft is not None
    assert result.draft.deadline_action is None
    assert TemporalType.CHECK_IN_TIME in {
        item.temporal_type for item in result.draft.temporal_fields
    }


def test_temporal_evidence_binds_image_frame_bbox_ocr_and_versions(tmp_path):
    image_path = tmp_path / "notice.bin"
    image_path.write_bytes(b"deterministic-notice-image")
    ocr = make_ocr(valid_rows(), source="frame-binding").model_copy(
        update={"image_path": image_path, "image_sha256": None}
    )
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.success is True and result.draft is not None
    field = result.draft.temporal_fields[0]
    binding = field.evidence
    assert binding.image_sha256 == hashlib.sha256(image_path.read_bytes()).hexdigest()
    assert binding.source_frame_id == "frame-binding"
    time_lines = ocr.evidence_lines[1:4]
    assert binding.evidence_line_ids == [line.line_id for line in time_lines]
    expected_bbox = (
        min(line.bbox[0] for line in time_lines),
        min(line.bbox[1] for line in time_lines),
        max(line.bbox[2] for line in time_lines),
        max(line.bbox[3] for line in time_lines),
    )
    assert binding.bbox == expected_bbox
    assert binding.ocr_text
    assert binding.normalized_value == field.value.isoformat()
    assert binding.ocr_confidence == field.confidence
    assert binding.ocr_version == "1"
    assert binding.extraction_rule_version == "deterministic-v2"
    assert binding.safety_gate_rule_version == "safety-gate-v1"


def test_safety_gate_blocks_temporal_field_with_missing_image_hash():
    ocr = make_ocr(valid_rows(), source="frame-no-image-hash").model_copy(
        update={"image_sha256": None}
    )
    result = DeterministicDraftExtractor().extract(ocr, CAPTURED_AT, "Asia/Shanghai")
    assert result.draft is not None
    decision = evaluate_notice(result.draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-TEMPORAL-001" in {
        rule.rule_id for rule in decision.rule_results if not rule.passed
    }


def test_temporal_model_rejects_forged_ocr_text_binding():
    result = _extract(valid_rows(), source="frame-forged-temporal")
    assert result.draft is not None
    payload = result.draft.temporal_fields[0].model_dump(mode="python")
    payload["source_text"] = "forged text"
    with pytest.raises(ValidationError):
        TemporalField.model_validate(payload)


@pytest.mark.parametrize(
    ("captured_at", "text", "expected"),
    [
        ("2026-08-01T16:30:00+00:00", "今晚 20:00", "2026-08-02T20:00:00+08:00"),
        ("2026-08-01T16:30:00+00:00", "明天下午 2:30", "2026-08-03T14:30:00+08:00"),
        ("2026-08-01T16:30:00+00:00", "下周一 09:00", "2026-08-03T09:00:00+08:00"),
        ("2026-12-31T08:00:00+08:00", "明天 09:00", "2027-01-01T09:00:00+08:00"),
        ("2028-02-28T08:00:00+08:00", "明天 09:00", "2028-02-29T09:00:00+08:00"),
    ],
)
def test_relative_time_boundaries_use_capture_time_and_user_timezone(
    captured_at, text, expected
):
    value, _ = normalize_relative_datetime(
        text, datetime.fromisoformat(captured_at), "Asia/Shanghai"
    )
    assert value is not None
    assert value.isoformat() == expected
    assert value.tzinfo == ZoneInfo("Asia/Shanghai")


def test_relative_time_without_clock_or_missing_year_is_not_guessed():
    captured_at = datetime.fromisoformat("2026-08-01T09:00:00+08:00")
    assert normalize_relative_datetime("明天下午", captured_at, "Asia/Shanghai")[0] is None
    result = _extract(
        [
            [("活动标题：摄影社交流活动", 0.98)],
            [("活动时间：8月7日 14:30", 0.96)],
            [("地点：大学生活动中心", 0.95)],
        ],
        source="frame-year-missing",
        captured_at=captured_at,
    )
    assert result.success is False
    assert result.suggested_status is SafetyGateStatus.NEED_USER_INPUT


def _extract_real_image(tmp_path, *, source="frame-real-evidence"):
    image_path = tmp_path / "notice.bin"
    image_path.write_bytes(b"trusted-notice-image")
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    ocr = make_ocr(valid_rows(), source=source).model_copy(
        update={"image_path": image_path, "image_sha256": digest}
    )
    result = DeterministicDraftExtractor().extract(
        ocr, CAPTURED_AT, "Asia/Shanghai"
    )
    assert result.success is True and result.draft is not None
    return image_path, ocr, result.draft


def test_image_changed_after_ocr_is_rejected_before_extraction(tmp_path):
    image_path = tmp_path / "notice.bin"
    image_path.write_bytes(b"original-image")
    original_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
    ocr = make_ocr(valid_rows(), source="frame-image-mutated-before-extraction").model_copy(
        update={"image_path": image_path, "image_sha256": original_hash}
    )
    image_path.write_bytes(b"mutated-image")
    result = DeterministicDraftExtractor().extract(
        ocr, CAPTURED_AT, "Asia/Shanghai"
    )
    assert result.success is False
    assert result.suggested_status is SafetyGateStatus.RECAPTURE_REQUIRED


def test_image_changed_after_extraction_is_blocked_by_safety_gate(tmp_path):
    image_path, _, draft = _extract_real_image(tmp_path)
    assert evaluate_notice(draft).status is SafetyGateStatus.READY_TO_CONFIRM
    image_path.write_bytes(b"mutated-after-extraction")
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-TEMPORAL-001" in {
        item.rule_id for item in decision.rule_results if not item.passed
    }


@pytest.mark.parametrize(
    "mutation",
    [
        "bbox",
        "line_id",
        "normalized_value",
        "ocr_text",
        "image_hash",
        "ocr_version",
        "extraction_rule_version",
        "safety_gate_rule_version",
    ],
)
def test_temporal_model_rejects_every_bound_evidence_mutation(tmp_path, mutation):
    _, _, draft = _extract_real_image(tmp_path, source=f"frame-mutate-{mutation}")
    payload = draft.temporal_fields[0].model_dump(mode="python")
    evidence = payload["evidence"]
    if mutation == "bbox":
        evidence["bbox"] = (1.0, 1.0, 2.0, 2.0)
    elif mutation == "line_id":
        evidence["evidence_line_ids"] = ["different-line"]
    elif mutation == "normalized_value":
        evidence["normalized_value"] = "2026-08-08T14:00:00+08:00"
    elif mutation == "ocr_text":
        evidence["ocr_text"] = "different OCR text"
    elif mutation == "image_hash":
        evidence["image_sha256"] = "f" * 64
    else:
        evidence[mutation] = "unexpected-version"
    with pytest.raises(ValidationError):
        TemporalField.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "tampered_value"),
    [
        ("bbox", (1.0, 1.0, 2.0, 2.0)),
        ("evidence_line_ids", ["different-line"]),
        ("ocr_text", "different OCR text"),
        ("normalized_value", "2026-08-08T14:00:00+08:00"),
        ("safety_gate_rule_version", "unexpected-version"),
    ],
)
def test_safety_gate_revalidates_model_copy_tampering(
    tmp_path, field_name, tampered_value
):
    _, _, draft = _extract_real_image(
        tmp_path, source=f"frame-model-copy-tamper-{field_name}"
    )
    field = draft.temporal_fields[0]
    tampered_evidence = field.evidence.model_copy(
        update={field_name: tampered_value}
    )
    tampered_field = field.model_copy(update={"evidence": tampered_evidence})
    tampered = draft.model_copy(update={"temporal_fields": [tampered_field]})
    decision = evaluate_notice(tampered)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-TEMPORAL-001" in {
        item.rule_id for item in decision.rule_results if not item.passed
    }


def test_deterministic_v2_cannot_bypass_temporal_semantics_with_empty_fields(tmp_path):
    _, _, draft = _extract_real_image(tmp_path, source="frame-empty-temporal")
    bypass = draft.model_copy(update={"temporal_fields": []})
    decision = evaluate_notice(bypass)
    assert decision.status is SafetyGateStatus.CONTRADICTION_BLOCKED
    assert "GF-TEMPORAL-001" in {
        item.rule_id for item in decision.rule_results if not item.passed
    }


def test_temporal_draft_json_round_trip_preserves_valid_evidence(tmp_path):
    _, _, draft = _extract_real_image(tmp_path, source="frame-json-roundtrip")
    serialized = draft.model_dump_json()
    restored = NoticePackageDraft.model_validate_json(serialized)
    assert restored.source_image_path is None
    assert restored.temporal_fields == draft.temporal_fields
    assert evaluate_notice(restored).status is SafetyGateStatus.READY_TO_CONFIRM
    assert "source_image_path" not in serialized


def test_calendar_preflight_rejects_draft_changed_after_safety_gate(tmp_path):
    _, _, draft = _extract_real_image(tmp_path, source="frame-preflight-binding")
    decision = evaluate_notice(draft)
    assert decision.status is SafetyGateStatus.READY_TO_CONFIRM
    changed_main = draft.main_event.model_copy(
        update={
            "event_start": datetime.fromisoformat("2026-08-08T14:00:00+08:00")
        }
    )
    changed_draft = draft.model_copy(update={"main_event": changed_main})
    service = TrustedSchedulingService(MemoryCalendarProvider())
    with pytest.raises(SchedulingValidationError, match="revalidation"):
        service.preflight(changed_draft, decision)
