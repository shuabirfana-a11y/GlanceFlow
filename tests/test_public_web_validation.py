from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

import glanceflow.evaluation.public_web as public_web_module
from glanceflow.evaluation.public_web import (
    CANDIDATE_FIELDS,
    MANIFEST_FIELDS,
    PublicWebManifestRow,
    compare_public_web_vs_synthetic,
    evaluate_public_web,
    load_manifest,
    ready_samples,
    validate_metadata,
)
from glanceflow.evaluation.public_web_preflight import (
    CacheRecord,
    PrivacyStatus,
    SanitizedRecord,
    ScopeStatus,
    inspect_image,
    is_evaluation_eligible,
    require_ready_for_formal_evaluation,
    run_preflight,
    weekday_matches,
)


PUBLIC_WEB_ROOT = Path("evaluation/real_data/public_web")
PUBLIC_WEB_LOCAL_CACHE = PUBLIC_WEB_ROOT / ".local_cache"
PUBLIC_WEB_SANITIZED_CACHE = PUBLIC_WEB_ROOT / ".sanitized_cache"
requires_public_web_local_cache = pytest.mark.skipif(
    not (PUBLIC_WEB_LOCAL_CACHE.is_dir() and PUBLIC_WEB_SANITIZED_CACHE.is_dir()),
    reason=(
        "requires the ignored, human-reviewed local PUBLIC_WEB caches; "
        "their absence is expected in a fresh collaborator clone"
    ),
)


def _row(**changes):
    row = {
        "sample_id": "PW-001", "source_type": "PUBLIC_WEB",
        "source_page_url": "https://university.example.edu/notice/1",
        "image_url": "https://university.example.edu/poster.jpg", "publisher": "Example University",
        "published_at": "2026-01-01", "accessed_at": "2026-08-03",
        "license": "NO_REUSE_LICENSE_FOUND", "redistribution_allowed": False,
        "privacy_reviewed": False, "local_file_committed": False,
        "annotation_status": "PAGE_TEXT_VERIFIED_IMAGE_PENDING", "scenario_type": "event_notice",
        "quality_tags": "poster", "local_cache_path": "evaluation/real_data/public_web/.local_cache/PW-001.jpg",
        "notes": "pending",
    }
    row.update(changes)
    return row


def test_public_web_source_type_is_separate():
    assert PublicWebManifestRow.model_validate(_row()).source_type == "PUBLIC_WEB"
    with pytest.raises(ValidationError):
        PublicWebManifestRow.model_validate(_row(source_type="REAL_CAMPUS_CAPTURE"))


def test_unlicensed_image_cannot_be_committed():
    with pytest.raises(ValidationError, match="must not be committed"):
        PublicWebManifestRow.model_validate(_row(local_file_committed=True))


def test_cache_must_be_in_ignored_directory():
    with pytest.raises(ValidationError, match="ignored local cache"):
        PublicWebManifestRow.model_validate(_row(local_cache_path="evaluation/real_data/public_web/PW-001.jpg"))


def test_repo_manifest_has_15_selected_official_records():
    rows = load_manifest()
    assert len(rows) == 15
    assert all(row.source_page_url.startswith("https://") for row in rows)
    assert all(not row.local_file_committed for row in rows)


def test_repo_candidate_pool_has_at_least_30_records():
    with Path("evaluation/real_data/public_web/public_web_candidates.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) >= 30
    assert set(row["status"] for row in rows) == {"SELECTED", "REJECTED"}


def test_independent_annotations_are_complete():
    rows, annotations = validate_metadata()
    assert len(rows) == len(annotations) == 15
    assert all(annotation.ground_truth_source == "OFFICIAL_PAGE_TEXT" for annotation in annotations)


def test_only_r01_approved_in_scope_samples_are_evaluation_ready():
    assert {row.sample_id for row, _ in ready_samples()} == {
        "PW-002", "PW-003", "PW-004", "PW-006", "PW-007",
        "PW-009", "PW-012", "PW-014", "PW-015",
    }


def _formal_result(sample_id: str) -> dict:
    return {
        "sample_id": sample_id, "input_type": "IMAGE", "ocr_success": True,
        "expected_title": "title", "predicted_title": "title",
        "expected_event_time": "2025-01-01T10:00:00+08:00",
        "predicted_event_time": "2025-01-01T10:00:00+08:00",
        "expected_location": "room", "predicted_location": "room",
        "expected_deadline": None, "predicted_deadline": None,
        "expected_behavior": "BUSINESS_COMPLETED",
        "agent_final_classification": "BUSINESS_COMPLETED",
        "business_completed": True, "safe_deferred": False, "safe_blocked": False,
        "recovery_pending": False, "wrong_execution": False, "system_failed": False,
        "confirmation_count": 1, "clarification_count": 0,
        "recapture_requested": False, "unsafe_tool_calls": 0,
        "confirmation_bypass": 0, "duplicate_execution": 0,
        "latency_ms": 1.0, "final_reason": "VERIFIED",
    }


@requires_public_web_local_cache
def test_public_web_evaluation_uses_lock_frozen_nine(monkeypatch, tmp_path):
    monkeypatch.setattr(
        public_web_module,
        "_evaluate_one",
        lambda row, annotation, sanitized_path: _formal_result(row.sample_id),
    )
    payload = evaluate_public_web(output_dir=tmp_path)
    summary = payload["summary"]
    assert payload["source_type"] == "PUBLIC_WEB"
    assert summary["status"] == "EXECUTED"
    assert summary["sample_count"] == 9
    assert summary["metrics"]["ocr_usable_rate"]["denominator"] == 9


@requires_public_web_local_cache
def test_public_outputs_name_public_web_not_real_campus(monkeypatch, tmp_path):
    monkeypatch.setattr(
        public_web_module,
        "_evaluate_one",
        lambda row, annotation, sanitized_path: _formal_result(row.sample_id),
    )
    evaluate_public_web(output_dir=tmp_path)
    text = (tmp_path / "public_web_report.md").read_text(encoding="utf-8")
    assert "Public-Web Real-World Notification" in text
    assert "real campus capture" not in text.lower()


def test_source_record_declares_no_committed_images():
    record = json.loads(Path("evaluation/real_data/public_web/source_records/sources.json").read_text(encoding="utf-8"))
    assert record["candidate_count"] >= 30
    assert record["selected_image_files_committed"] == 0
    assert all(not item["redistribution_allowed"] for item in record["selected_records"])


@requires_public_web_local_cache
def test_comparison_uses_correct_dataset_labels(monkeypatch, tmp_path):
    result_dir = tmp_path / "results"
    monkeypatch.setattr(
        public_web_module,
        "_evaluate_one",
        lambda row, annotation, sanitized_path: _formal_result(row.sample_id),
    )
    evaluate_public_web(output_dir=result_dir)
    payload = compare_public_web_vs_synthetic(public_web_path=result_dir / "public_web_results.json", output_dir=result_dir)
    assert payload["scope"] == "Synthetic Evaluation Set vs Public-Web Real-World Notification Set"
    assert payload["public_web"]["status"] == "EXECUTED"
    assert payload["public_web"]["sample_count"] == 9
    assert payload["statistical_significance_claimed"] is False


def test_gitignore_excludes_public_web_cache():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "evaluation/real_data/public_web/.local_cache/" in text
    assert "evaluation/real_data/public_web/.sanitized_cache/" in text


def _valid_cache(**changes):
    row = {
        "sample_id": "PW-001", "source_url": "https://university.example/notice",
        "local_cache_path": "evaluation/real_data/public_web/.local_cache/PW-001.png",
        "download_status": "VALID", "file_size": 4096, "file_type": "PNG",
        "width": 640, "height": 480, "sha256": "a" * 64,
        "downloaded_at": "2026-08-03T00:00:00+00:00", "duplicate": False,
        "duplicate_of": None, "download_error": "",
    }
    row.update(changes)
    return CacheRecord.model_validate(row)


def _eligible(**changes):
    args = {
        "source_valid": True, "cache": _valid_cache(),
        "sanitized_valid": True,
        "privacy_status": PrivacyStatus.CLEAR.value, "ground_truth_complete": True,
        "scope_status": ScopeStatus.IN_SCOPE.value, "review_status": "APPROVED",
        "reviewer": "R01", "annotation_status": "APPROVED",
        "annotation_reviewed": True,
    }
    args.update(changes)
    return is_evaluation_eligible(**args)


def test_image_integrity_records_dimensions_and_sha256(tmp_path):
    path = tmp_path / "poster.png"
    Image.new("RGB", (640, 480), "white").save(path)
    result = inspect_image(path)
    assert result["file_type"] == "PNG"
    assert result["width"] == 640 and result["height"] == 480
    assert len(result["sha256"]) == 64


def test_html_disguised_as_image_is_rejected(tmp_path):
    path = tmp_path / "poster.jpg"
    path.write_text("<!doctype html><title>403</title>", encoding="utf-8")
    with pytest.raises(ValueError, match="HTML_NOT_IMAGE"):
        inspect_image(path)


def test_low_resolution_placeholder_is_rejected(tmp_path):
    path = tmp_path / "tiny.png"
    Image.new("RGB", (64, 64), "white").save(path)
    with pytest.raises(ValueError, match="LOW_RESOLUTION"):
        inspect_image(path)


def test_valid_download_requires_sha256():
    with pytest.raises(ValidationError, match="sha256"):
        _valid_cache(sha256=None)


def test_duplicate_image_is_not_eligible():
    assert not _eligible(cache=_valid_cache(duplicate=True, duplicate_of="PW-000"))


def test_missing_sanitized_image_is_not_eligible():
    assert not _eligible(sanitized_valid=False)


def test_codex_cannot_be_human_reviewer():
    assert not _eligible(reviewer="CODEX")


@pytest.mark.parametrize("status", [PrivacyStatus.REVIEW_REQUIRED.value, PrivacyStatus.REJECTED.value])
def test_unresolved_or_rejected_privacy_is_not_eligible(status):
    assert not _eligible(privacy_status=status)


def test_redacted_privacy_can_be_eligible_after_all_other_gates():
    assert _eligible(privacy_status=PrivacyStatus.REDACTED.value)


def test_sanitized_record_must_be_separate_and_changed():
    values = {
        "sample_id": "PW-001",
        "sanitized_path": "evaluation/real_data/public_web/.sanitized_cache/PW-001.png",
        "original_sha256": "a" * 64,
        "sanitized_sha256": "b" * 64,
        "file_size": 4096,
        "file_type": "PNG",
        "width": 640,
        "height": 480,
        "duplicate": False,
        "duplicate_of": None,
    }
    assert SanitizedRecord.model_validate(values).sample_id == "PW-001"
    values["sanitized_path"] = "evaluation/real_data/public_web/.local_cache/PW-001.png"
    with pytest.raises(ValidationError, match="ignored sanitized cache"):
        SanitizedRecord.model_validate(values)


def test_incomplete_ground_truth_is_not_eligible():
    assert not _eligible(ground_truth_complete=False)


def test_out_of_scope_is_traceable_but_not_eligible():
    assert not _eligible(scope_status=ScopeStatus.OUT_OF_SCOPE.value)


def test_weekday_validation_detects_real_contradiction():
    assert weekday_matches("2025-04-15", "星期二")
    assert not weekday_matches("2025-04-15", "星期三")


def test_deadline_and_event_start_cannot_be_identical():
    raw = json.loads(Path("evaluation/real_data/public_web/annotations/PW-002.json").read_text(encoding="utf-8"))
    raw["deadline"] = raw["event_start"]
    from glanceflow.evaluation.public_web import PublicWebAnnotation
    with pytest.raises(ValidationError, match="must not be conflated"):
        PublicWebAnnotation.model_validate(raw)


def test_repo_annotations_record_only_r01_human_approvals():
    _, annotations = validate_metadata()
    approved = {item.sample_id for item in annotations if item.human_review_status == "APPROVED"}
    assert approved == {
        "PW-002", "PW-003", "PW-004", "PW-006", "PW-007",
        "PW-009", "PW-012", "PW-014", "PW-015",
    }
    assert all(item.reviewer == "R01" and item.ground_truth_reviewed for item in annotations if item.sample_id in approved)
    assert all(item.reviewer is None and not item.ground_truth_reviewed for item in annotations if item.sample_id not in approved)


@requires_public_web_local_cache
def test_preflight_lock_matches_eligible_set_and_allows_formal_run(tmp_path):
    lock = tmp_path / "evaluation_set.lock.json"
    audit = tmp_path / "audit.md"
    summary = run_preflight(lock_path=lock, audit_path=audit)
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert summary["EVALUATION_ELIGIBLE"] == payload["sample_count"] == 9
    assert payload["status"] == "READY"
    assert require_ready_for_formal_evaluation(lock) == payload["sample_ids"]


def test_not_ready_lock_blocks_formal_run(tmp_path):
    lock = tmp_path / "evaluation_set.lock.json"
    lock.write_text(json.dumps({"status": "NOT_READY", "sample_ids": []}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="formal OCR/Agent evaluation is forbidden"):
        require_ready_for_formal_evaluation(lock)
