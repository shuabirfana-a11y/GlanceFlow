from __future__ import annotations

import argparse
import csv
import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


ROOT = Path("evaluation/real_world")
DEFAULT_MANIFEST = ROOT / "manifest.csv"
DEFAULT_OUTPUT = Path("outputs/real_world/preflight.json")
MANIFEST_FIELDS = (
    "sample_id", "source_type", "capture_date", "permission_status", "sanitized",
    "contains_name", "contains_phone", "contains_student_id", "contains_qr", "contains_face",
    "allowed_for_repository", "allowed_for_demo", "image_path", "sha256", "annotation_path",
    "source_url", "license", "attribution",
)


class SourceType(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    PUBLIC_WEB = "PUBLIC_WEB"
    REAL_CAMPUS_LOCAL = "REAL_CAMPUS_LOCAL"
    REAL_CAMPUS_PUBLIC = "REAL_CAMPUS_PUBLIC"


class ManifestRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str = Field(min_length=1, pattern=r"^[A-Z0-9-]+$")
    source_type: SourceType
    capture_date: str
    permission_status: str = Field(min_length=1)
    sanitized: bool
    contains_name: bool
    contains_phone: bool
    contains_student_id: bool
    contains_qr: bool
    contains_face: bool
    allowed_for_repository: bool
    allowed_for_demo: bool
    image_path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    annotation_path: Path
    source_url: str = ""
    license: str = ""
    attribution: str = ""

    @model_validator(mode="after")
    def public_safety(self) -> "ManifestRow":
        sensitive = self.contains_name or self.contains_phone or self.contains_student_id or self.contains_qr or self.contains_face
        if self.allowed_for_repository and (not self.sanitized or sensitive):
            raise ValueError("repository samples must be sanitized and privacy-clear")
        if self.source_type is SourceType.REAL_CAMPUS_LOCAL and self.allowed_for_repository:
            raise ValueError("REAL_CAMPUS_LOCAL must remain outside the repository")
        if self.allowed_for_repository and self.permission_status != "VERIFIED":
            raise ValueError("repository samples require VERIFIED permission")
        if self.source_type is SourceType.PUBLIC_WEB and self.allowed_for_repository and not self.license:
            raise ValueError("redistributed PUBLIC_WEB samples require a license")
        return self


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ocr_line: str
    bbox: list[float] = Field(min_length=4, max_length=4)
    source_frame: str


class RealWorldGroundTruth(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_id: str
    title: str | None = None
    event_start: str | None = None
    event_end: str | None = None
    location: str | None = None
    registration_deadline: str | None = None
    submission_deadline: str | None = None
    checkin_time: str | None = None
    publish_time: str | None = None
    cancellation: bool = False
    reschedule: bool = False
    temporal_roles: list[str] = Field(default_factory=list)
    ambiguity: list[str] = Field(default_factory=list)
    executable: bool
    evidence: dict[str, Evidence] = Field(default_factory=dict)
    annotation_status: str
    annotator: str
    reviewer: str


def _bool(value: str, field: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError(f"{field} must be true or false")
    return value.lower() == "true"


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[ManifestRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
            raise ValueError("manifest header does not match the Stage 13 schema")
        raw = [r for r in reader if any((v or "").strip() for v in r.values())]
    rows: list[ManifestRow] = []
    for item in raw:
        converted: dict[str, Any] = dict(item)
        for field in ("sanitized", "contains_name", "contains_phone", "contains_student_id", "contains_qr", "contains_face", "allowed_for_repository", "allowed_for_demo"):
            converted[field] = _bool(item[field], field)
        rows.append(ManifestRow.model_validate(converted))
    if len({r.sample_id for r in rows}) != len(rows):
        raise ValueError("sample_id must be unique")
    return rows


def run_preflight(manifest_path: Path = DEFAULT_MANIFEST, output_path: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    rows = load_manifest(manifest_path)
    repo_root = manifest_path.resolve().parents[2]
    validated: list[str] = []
    for row in rows:
        image = (repo_root / row.image_path).resolve()
        annotation = (repo_root / row.annotation_path).resolve()
        if not image.is_file():
            raise ValueError(f"{row.sample_id}: image missing")
        if hashlib.sha256(image.read_bytes()).hexdigest() != row.sha256:
            raise ValueError(f"{row.sample_id}: image hash mismatch")
        if not annotation.is_file():
            raise ValueError(f"{row.sample_id}: annotation missing")
        truth = RealWorldGroundTruth.model_validate_json(annotation.read_text(encoding="utf-8"))
        if truth.sample_id != row.sample_id or truth.annotation_status != "APPROVED":
            raise ValueError(f"{row.sample_id}: ground truth is not independently approved")
        validated.append(row.sample_id)
    real_ids = [r.sample_id for r in rows if r.source_type in {SourceType.REAL_CAMPUS_LOCAL, SourceType.REAL_CAMPUS_PUBLIC}]
    public_ids = [r.sample_id for r in rows if r.allowed_for_repository]
    payload = {
        "STATUS": "READY" if real_ids else "WAITING_FOR_DATA",
        "REAL_CAMPUS_SAMPLE_COUNT": len(real_ids),
        "PUBLIC_REPOSITORY_SAMPLE_COUNT": len(public_ids),
        "LOCAL_PRIVATE_SAMPLE_COUNT": sum(r.source_type is SourceType.REAL_CAMPUS_LOCAL for r in rows),
        "GROUND_TRUTH_COMPLETE_COUNT": len(validated),
        "validated_sample_ids": validated,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Stage 13 real-world data before evaluation")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(run_preflight(args.manifest, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
