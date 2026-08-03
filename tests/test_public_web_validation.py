from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
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
