from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

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
    ScopeStatus,
    inspect_image,
    is_evaluation_eligible,
    require_ready_for_formal_evaluation,
    run_preflight,
    weekday_matches,
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


def test_pending_visual_review_is_not_evaluation_ready():
    assert ready_samples() == []


def test_public_web_evaluation_does_not_invent_zero_rates(tmp_path):
    payload = evaluate_public_web(output_dir=tmp_path)
    summary = payload["summary"]
    assert summary["status"] == "NOT_EXECUTED_LOCAL_CACHE_UNAVAILABLE"
    assert summary["sample_count"] == 0
    assert summary["metrics"] == {}
    assert all(value is None for value in summary["outcome_counts"].values())


def test_public_outputs_name_public_web_not_real_campus(tmp_path):
    evaluate_public_web(output_dir=tmp_path)
    text = (tmp_path / "public_web_report.md").read_text(encoding="utf-8")
    assert "Public-Web Real-World Notification" in text
    assert "real campus capture" not in text.lower()


def test_source_record_declares_no_committed_images():
    record = json.loads(Path("evaluation/real_data/public_web/source_records/sources.json").read_text(encoding="utf-8"))
    assert record["candidate_count"] >= 30
    assert record["selected_image_files_committed"] == 0
    assert all(not item["redistribution_allowed"] for item in record["selected_records"])


def test_comparison_uses_correct_dataset_labels(tmp_path):
    result_dir = tmp_path / "results"
    evaluate_public_web(output_dir=result_dir)
    payload = compare_public_web_vs_synthetic(public_web_path=result_dir / "public_web_results.json", output_dir=result_dir)
    assert payload["scope"] == "Synthetic Evaluation Set vs Public-Web Real-World Notification Set"
    assert payload["public_web"]["status"].startswith("NOT_EXECUTED")
    assert payload["statistical_significance_claimed"] is False


def test_gitignore_excludes_public_web_cache():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "evaluation/real_data/public_web/.local_cache/" in text


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
        "privacy_status": PrivacyStatus.CLEAR.value, "ground_truth_complete": True,
        "scope_status": ScopeStatus.IN_SCOPE.value, "review_status": "APPROVED",
        "annotation_status": "APPROVED",
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


@pytest.mark.parametrize("status", [PrivacyStatus.REVIEW_REQUIRED.value, PrivacyStatus.REJECTED.value])
def test_unresolved_or_rejected_privacy_is_not_eligible(status):
    assert not _eligible(privacy_status=status)


def test_redacted_privacy_can_be_eligible_after_all_other_gates():
    assert _eligible(privacy_status=PrivacyStatus.REDACTED.value)


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


def test_repo_annotations_do_not_invent_human_reviewers():
    _, annotations = validate_metadata()
    assert all(item.reviewer is None for item in annotations)
    assert all(item.human_review_status == "PENDING" for item in annotations)
    assert all(not item.ground_truth_reviewed for item in annotations)


def test_preflight_lock_matches_eligible_set_and_blocks_formal_run(tmp_path):
    lock = tmp_path / "evaluation_set.lock.json"
    audit = tmp_path / "audit.md"
    summary = run_preflight(lock_path=lock, audit_path=audit)
    payload = json.loads(lock.read_text(encoding="utf-8"))
    assert summary["EVALUATION_ELIGIBLE"] == payload["sample_count"] == 0
    assert payload["sample_ids"] == [] and payload["status"] == "NOT_READY"
    with pytest.raises(RuntimeError, match="formal OCR/Agent evaluation is forbidden"):
        require_ready_for_formal_evaluation(lock)
