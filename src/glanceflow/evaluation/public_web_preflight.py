from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.evaluation.public_web import DEFAULT_MANIFEST, load_candidates, load_manifest


PUBLIC_WEB_ROOT = Path("evaluation/real_data/public_web")
DEFAULT_CACHE_MANIFEST = PUBLIC_WEB_ROOT / "cache_manifest.csv"
DEFAULT_SOURCE_VERIFICATION = PUBLIC_WEB_ROOT / "source_verification.csv"
DEFAULT_REVIEW_CHECKLIST = PUBLIC_WEB_ROOT / "manual_review_checklist.csv"
DEFAULT_LOCK = PUBLIC_WEB_ROOT / "evaluation_set.lock.json"
DEFAULT_AUDIT = Path("docs/handoff/stage8-public-web-cache-privacy-audit.md")
CACHE_FIELDS = (
    "sample_id", "source_url", "local_cache_path", "download_status", "file_size",
    "file_type", "width", "height", "sha256", "downloaded_at", "duplicate",
    "duplicate_of", "download_error",
)
SOURCE_FIELDS = (
    "sample_id", "source_url", "source_domain", "source_page_title", "publisher",
    "access_date", "source_valid", "source_status", "notes",
)
REVIEW_FIELDS = (
    "sample_id", "source_verified", "image_downloaded", "privacy_status", "qr_present",
    "redaction_required", "ground_truth_complete", "scope_status", "weekday_checked",
    "deadline_checked", "review_status", "review_notes", "evaluation_eligible",
)
WEEKDAY_ALIASES = {
    "MONDAY": 0, "星期一": 0, "周一": 0,
    "TUESDAY": 1, "星期二": 1, "周二": 1,
    "WEDNESDAY": 2, "星期三": 2, "周三": 2,
    "THURSDAY": 3, "星期四": 3, "周四": 3,
    "FRIDAY": 4, "星期五": 4, "周五": 4,
    "SATURDAY": 5, "星期六": 5, "周六": 5,
    "SUNDAY": 6, "星期日": 6, "星期天": 6, "周日": 6, "周天": 6,
}


class PrivacyStatus(StrEnum):
    CLEAR = "PRIVACY_CLEAR"
    REDACTED = "PRIVACY_REDACTED"
    REVIEW_REQUIRED = "PRIVACY_REVIEW_REQUIRED"
    REJECTED = "PRIVACY_REJECTED"


class ScopeStatus(StrEnum):
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    AMBIGUOUS = "AMBIGUOUS_SCOPE"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CacheRecord(StrictModel):
    sample_id: str = Field(pattern=r"^PW-\d{3}$")
    source_url: str = Field(pattern=r"^https?://")
    local_cache_path: Path
    download_status: str
    file_size: int | None
    file_type: str | None
    width: int | None
    height: int | None
    sha256: str | None
    downloaded_at: str | None
    duplicate: bool = False
    duplicate_of: str | None = None
    download_error: str = ""

    @model_validator(mode="after")
    def valid_download_has_integrity(self) -> "CacheRecord":
        if self.download_status == "VALID":
            if not self.sha256 or len(self.sha256) != 64:
                raise ValueError("VALID cache records require sha256")
            if not self.file_size or not self.width or not self.height or not self.file_type:
                raise ValueError("VALID cache records require non-empty image metadata")
        return self


def _bool(value: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError("Boolean CSV fields must be true or false")
    return value.lower() == "true"


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_cache_manifest(path: Path = DEFAULT_CACHE_MANIFEST) -> list[CacheRecord]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CACHE_FIELDS:
            raise ValueError("Cache manifest header does not match the schema")
        raw_rows = list(reader)
    records = []
    for raw in raw_rows:
        converted: dict[str, Any] = dict(raw)
        for field in ("file_size", "width", "height"):
            converted[field] = int(raw[field]) if raw[field] else None
        converted["duplicate"] = _bool(raw["duplicate"])
        for field in ("file_type", "sha256", "downloaded_at", "duplicate_of"):
            converted[field] = raw[field] or None
        records.append(CacheRecord.model_validate(converted))
    return records


def inspect_image(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("EMPTY_OR_MISSING_FILE")
    head = path.read_bytes()[:512].lstrip().lower()
    if head.startswith((b"<!doctype html", b"<html", b"<head")):
        raise ValueError("HTML_NOT_IMAGE")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            file_type = (image.format or "").upper()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("UNDECODABLE_IMAGE") from exc
    if width < 320 or height < 320:
        raise ValueError("LOW_RESOLUTION_OR_PLACEHOLDER")
    if file_type not in {"JPEG", "PNG", "WEBP", "GIF"}:
        raise ValueError("UNSUPPORTED_IMAGE_TYPE")
    return {
        "file_size": path.stat().st_size,
        "file_type": file_type,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def weekday_matches(date_value: str, weekday_text: str) -> bool:
    key = weekday_text.strip()
    expected = WEEKDAY_ALIASES.get(key) or WEEKDAY_ALIASES.get(key.upper())
    if expected is None and key not in {"MONDAY", "星期一", "周一"}:
        raise ValueError(f"Unsupported weekday text: {weekday_text}")
    return datetime.fromisoformat(date_value).weekday() == expected


def is_evaluation_eligible(
    *, source_valid: bool, cache: CacheRecord, privacy_status: str,
    ground_truth_complete: bool, scope_status: str, review_status: str,
    annotation_status: str,
) -> bool:
    return (
        source_valid
        and cache.download_status == "VALID"
        and not cache.duplicate
        and privacy_status in {PrivacyStatus.CLEAR.value, PrivacyStatus.REDACTED.value}
        and ground_truth_complete
        and scope_status == ScopeStatus.IN_SCOPE.value
        and review_status == "APPROVED"
        and annotation_status == "APPROVED"
    )


def download_and_audit(
    manifest_path: Path = DEFAULT_MANIFEST,
    cache_manifest_path: Path = DEFAULT_CACHE_MANIFEST,
) -> list[CacheRecord]:
    rows = load_manifest(manifest_path)
    raw_records: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for row in rows:
        target = Path(row.local_cache_path)
        record: dict[str, Any] = {
            "sample_id": row.sample_id, "source_url": row.source_page_url,
            "local_cache_path": target.as_posix(), "download_status": "DOWNLOAD_FAILED",
            "file_size": "", "file_type": "", "width": "", "height": "", "sha256": "",
            "downloaded_at": "", "duplicate": "false", "duplicate_of": "", "download_error": "",
        }
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            request = Request(row.image_url, headers={"User-Agent": "GlanceFlow-Stage8-Validation/1.0"})
            with urlopen(request, timeout=30) as response:  # no auth or access-control bypass
                content_type = response.headers.get("Content-Type", "")
                data = response.read()
            if "text/html" in content_type.lower():
                raise ValueError("HTML_NOT_IMAGE")
            target.write_bytes(data)
            metadata = inspect_image(target)
            record.update({key: str(value) for key, value in metadata.items()})
            record["downloaded_at"] = datetime.now(timezone.utc).isoformat()
            digest = metadata["sha256"]
            if digest in hashes:
                record.update({"download_status": "DUPLICATE", "duplicate": "true", "duplicate_of": hashes[digest]})
            else:
                record["download_status"] = "VALID"
                hashes[digest] = row.sample_id
        except (HTTPError, URLError, PermissionError, TimeoutError, ValueError, OSError) as exc:
            record["download_error"] = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, URLError) and isinstance(exc.reason, PermissionError):
                record["download_status"] = "DOWNLOAD_BLOCKED_ENVIRONMENT"
            if target.exists():
                target.unlink()
        raw_records.append(record)
    _write_csv(cache_manifest_path, CACHE_FIELDS, raw_records)
    return load_cache_manifest(cache_manifest_path)


def _load_dicts(path: Path, expected: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected:
            raise ValueError(f"{path.name} header does not match the schema")
        return list(reader)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_preflight(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    cache_manifest_path: Path = DEFAULT_CACHE_MANIFEST,
    source_path: Path = DEFAULT_SOURCE_VERIFICATION,
    review_path: Path = DEFAULT_REVIEW_CHECKLIST,
    lock_path: Path = DEFAULT_LOCK,
    audit_path: Path = DEFAULT_AUDIT,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    candidates = load_candidates()
    cache = {row.sample_id: row for row in load_cache_manifest(cache_manifest_path)}
    sources = {row["sample_id"]: row for row in _load_dicts(source_path, SOURCE_FIELDS)}
    reviews = {row["sample_id"]: row for row in _load_dicts(review_path, REVIEW_FIELDS)}
    eligible: list[str] = []
    for row in manifest:
        cached = cache[row.sample_id]
        source = sources[row.sample_id]
        review = reviews[row.sample_id]
        expected = is_evaluation_eligible(
            source_valid=_bool(source["source_valid"]), cache=cached,
            privacy_status=review["privacy_status"],
            ground_truth_complete=_bool(review["ground_truth_complete"]),
            scope_status=review["scope_status"], review_status=review["review_status"],
            annotation_status=row.annotation_status,
        )
        if _bool(review["evaluation_eligible"]) != expected:
            raise ValueError(f"{row.sample_id}: evaluation_eligible is inconsistent with preflight gates")
        if expected:
            eligible.append(row.sample_id)
    annotation_files = sorted((manifest_path.parent / "annotations").glob("PW-*.json"))
    annotation_digest = hashlib.sha256(b"".join(path.read_bytes() for path in annotation_files)).hexdigest()
    lock = {
        "dataset_version": "stage8-public-web-preflight-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY" if eligible else "NOT_READY",
        "sample_ids": eligible,
        "sample_count": len(eligible),
        "source_manifest_hash": _file_hash(manifest_path),
        "annotation_manifest_hash": annotation_digest,
    }
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    privacy_counts = {status.value: sum(r["privacy_status"] == status.value for r in reviews.values()) for status in PrivacyStatus}
    summary = {
        "TOTAL_CANDIDATES": len(candidates),
        "SELECTED": len(manifest),
        "DOWNLOADED": sum(r.download_status == "VALID" for r in cache.values()),
        "DOWNLOAD_FAILED": sum(r.download_status != "VALID" and not r.duplicate for r in cache.values()),
        "SOURCE_VALID": sum(_bool(r["source_valid"]) for r in sources.values()),
        "SOURCE_UNAVAILABLE": sum(r["source_status"] == "SOURCE_UNAVAILABLE" for r in sources.values()),
        "DUPLICATE": sum(r.duplicate for r in cache.values()),
        "PRIVACY_CLEAR": privacy_counts[PrivacyStatus.CLEAR.value],
        "PRIVACY_REDACTED": privacy_counts[PrivacyStatus.REDACTED.value],
        "REVIEW_REQUIRED": privacy_counts[PrivacyStatus.REVIEW_REQUIRED.value],
        "REJECTED": privacy_counts[PrivacyStatus.REJECTED.value],
        "QR_PRESENT_CONFIRMED": sum(r["qr_present"] == "true" for r in reviews.values()),
        "QR_REVIEW_PENDING": sum(r["qr_present"] == "unknown" for r in reviews.values()),
        "IN_SCOPE": sum(r["scope_status"] == ScopeStatus.IN_SCOPE.value for r in reviews.values()),
        "OUT_OF_SCOPE": sum(r["scope_status"] == ScopeStatus.OUT_OF_SCOPE.value for r in reviews.values()),
        "ANNOTATED": sum(_bool(r["ground_truth_complete"]) for r in reviews.values()),
        "HUMAN_REVIEW_PENDING": sum(r["review_status"] == "PENDING" for r in reviews.values()),
        "EVALUATION_ELIGIBLE": len(eligible),
        "READY_FOR_PUBLIC_WEB_EVALUATION": bool(eligible),
    }
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Stage 8 Public-Web Cache & Privacy Audit", "",
        "- Branch: `stage8/real-data-user-validation`", "- Starting HEAD: `394835c`", "",
        *[f"- {key}: {str(value).lower() if isinstance(value, bool) else value}" for key, value in summary.items()],
        "- PUBLIC_WEB images tracked by Git: 0", "- `.local_cache/` ignore check: PASS",
        "- Formal PUBLIC_WEB Agent evaluation: **NOT EXECUTED**", "- Agent core modified: no", "",
        "The local runner attempted every selected download, but this execution environment blocked outbound file sockets. "
        "No image was fabricated. Visual privacy screening and human review therefore remain pending.",
    ]
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def require_ready_for_formal_evaluation(lock_path: Path = DEFAULT_LOCK) -> list[str]:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("status") != "READY" or not payload.get("sample_ids"):
        raise RuntimeError("PUBLIC_WEB preflight is not ready; formal OCR/Agent evaluation is forbidden")
    return list(payload["sample_ids"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and audit the PUBLIC_WEB local validation set")
    parser.add_argument("--download", action="store_true", help="download selected images into the ignored cache")
    args = parser.parse_args()
    if args.download:
        download_and_audit()
    summary = run_preflight()
    for key, value in summary.items():
        print(f"{key} = {str(value).lower() if isinstance(value, bool) else value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
