from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from glanceflow.evaluation.real_world import evaluate
from glanceflow.evaluation.real_world_preflight import MANIFEST_FIELDS, load_manifest, run_preflight


def _manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_repository_manifest_is_waiting_for_real_data(tmp_path):
    result = run_preflight(output_path=tmp_path / "preflight.json")
    assert result["STATUS"] == "WAITING_FOR_DATA"
    assert result["REAL_CAMPUS_SAMPLE_COUNT"] == 0
    assert load_manifest() == []


def test_zero_data_metrics_are_not_fabricated(tmp_path):
    result = evaluate(output_dir=tmp_path)
    assert result["STATUS"] == "WAITING_FOR_DATA"
    assert all(metric["denominator"] == 0 and metric["value"] is None for metric in result["metrics"].values())
    assert (tmp_path / "sample_results.csv").read_text(encoding="utf-8-sig").startswith("sample_id,")


def test_duplicate_sample_ids_are_rejected(tmp_path):
    manifest = tmp_path / "manifest.csv"
    row = {field: "" for field in MANIFEST_FIELDS}
    row.update(sample_id="RW-001", source_type="REAL_CAMPUS_LOCAL", capture_date="2026-08-07", permission_status="LOCAL_ONLY", sanitized="false", contains_name="false", contains_phone="false", contains_student_id="false", contains_qr="false", contains_face="false", allowed_for_repository="false", allowed_for_demo="false", image_path="missing.jpg", sha256="a" * 64, annotation_path="missing.json")
    _manifest(manifest, [row, row])
    with pytest.raises(ValueError, match="unique"):
        load_manifest(manifest)


def test_unreviewed_sensitive_file_cannot_be_public(tmp_path):
    manifest = tmp_path / "manifest.csv"
    row = {field: "" for field in MANIFEST_FIELDS}
    row.update(sample_id="PW-001", source_type="PUBLIC_WEB", capture_date="2026-08-07", permission_status="VERIFIED", sanitized="true", contains_name="true", contains_phone="false", contains_student_id="false", contains_qr="false", contains_face="false", allowed_for_repository="true", allowed_for_demo="false", image_path="x.jpg", sha256="a" * 64, annotation_path="x.json", license="CC BY-SA 4.0")
    _manifest(manifest, [row])
    with pytest.raises(ValueError, match="privacy-clear"):
        load_manifest(manifest)


def test_hash_mismatch_is_rejected(tmp_path):
    root = tmp_path / "repo"
    data = root / "evaluation" / "real_world"
    data.mkdir(parents=True)
    image = data / "image.jpg"
    image.write_bytes(b"image")
    annotation = data / "annotation.json"
    annotation.write_text(json.dumps({"sample_id": "PW-001", "executable": False, "annotation_status": "APPROVED", "annotator": "A01", "reviewer": "R01"}), encoding="utf-8")
    row = {field: "" for field in MANIFEST_FIELDS}
    row.update(sample_id="PW-001", source_type="PUBLIC_WEB", capture_date="2026-08-07", permission_status="VERIFIED", sanitized="true", contains_name="false", contains_phone="false", contains_student_id="false", contains_qr="false", contains_face="false", allowed_for_repository="true", allowed_for_demo="true", image_path="evaluation/real_world/image.jpg", sha256=hashlib.sha256(b"wrong").hexdigest(), annotation_path="evaluation/real_world/annotation.json", license="CC BY-SA 4.0")
    manifest = data / "manifest.csv"
    _manifest(manifest, [row])
    with pytest.raises(ValueError, match="hash mismatch"):
        run_preflight(manifest, tmp_path / "out.json")


def test_private_directories_are_ignored():
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "evaluation/real_world/raw/" in text
    assert "evaluation/real_world/private/" in text


def test_public_web_candidates_are_not_called_real_campus():
    text = Path("evaluation/real_world/public_web_candidates.md").read_text(encoding="utf-8")
    assert "not real campus captures" in text
    assert "CC BY-SA 4.0" in text
