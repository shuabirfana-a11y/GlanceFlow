from datetime import datetime

import pytest
from pydantic import ValidationError

from glanceflow.domain.models import EvidenceLine, NoticePackageDraft


def test_model_validation_and_bbox(payload_factory):
    draft = NoticePackageDraft.model_validate(payload_factory())
    assert draft.notice_package_id == "GF-PKG-0001"
    assert draft.evidence_lines[0].bbox == (10.0, 10.0, 300.0, 40.0)

    with pytest.raises(ValidationError):
        EvidenceLine(line_id="x", text="x", confidence=1.1, source_frame_id="frame")


@pytest.mark.parametrize("package_id", ["GF-PKG-1", "PKG-0001", "GF-PKG-00001"])
def test_id_format_rejected(payload_factory, package_id):
    payload = payload_factory()
    payload["notice_package_id"] = package_id
    with pytest.raises(ValidationError):
        NoticePackageDraft.model_validate(payload)


def test_json_serialization_round_trip(draft_factory):
    original = draft_factory(with_deadline=True)
    restored = NoticePackageDraft.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.deadline_action is not None


def test_duplicate_evidence_line_id_rejected(payload_factory):
    payload = payload_factory()
    payload["evidence_lines"][1]["line_id"] = "ocr-01"
    with pytest.raises(ValidationError):
        NoticePackageDraft.model_validate(payload)


@pytest.mark.parametrize("field_path", ["captured_at", "event_start", "deadline"])
def test_timezone_required(payload_factory, field_path):
    payload = payload_factory(with_deadline=True)
    if field_path == "captured_at":
        payload["captured_at"] = datetime(2026, 8, 1, 9, 0)
    elif field_path == "event_start":
        payload["main_event"]["event_start"] = datetime(2026, 8, 7, 14, 0)
    else:
        payload["deadline_action"]["deadline"] = datetime(2026, 8, 6, 20, 0)
    with pytest.raises(ValidationError):
        NoticePackageDraft.model_validate(payload)
