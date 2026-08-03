from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.evaluation.real_comparison import COMPARISON_METRICS, summarize_synthetic
from glanceflow.evaluation.real_data import OUTCOMES


DEFAULT_ROOT = Path("evaluation/real_data/public_web")
DEFAULT_MANIFEST = DEFAULT_ROOT / "manifest.csv"
DEFAULT_CANDIDATES = DEFAULT_ROOT / "public_web_candidates.csv"
DEFAULT_OUTPUT = Path("outputs/evaluation/public_web")
MANIFEST_FIELDS = (
    "sample_id", "source_type", "source_page_url", "image_url", "publisher",
    "published_at", "accessed_at", "license", "redistribution_allowed",
    "privacy_reviewed", "local_file_committed", "annotation_status",
    "scenario_type", "quality_tags", "local_cache_path", "notes",
)
CANDIDATE_FIELDS = (
    "candidate_id", "source_page_url", "publisher", "published_at", "status",
    "reason", "image_url",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicWebManifestRow(StrictModel):
    sample_id: str = Field(pattern=r"^PW-\d{3}$")
    source_type: Literal["PUBLIC_WEB"]
    source_page_url: str = Field(pattern=r"^https?://")
    image_url: str = Field(pattern=r"^https?://")
    publisher: str = Field(min_length=1)
    published_at: str
    accessed_at: str
    license: str = Field(min_length=1)
    redistribution_allowed: bool
    privacy_reviewed: bool
    local_file_committed: bool
    annotation_status: Literal["APPROVED", "PAGE_TEXT_VERIFIED_IMAGE_PENDING", "REJECTED"]
    scenario_type: str = Field(min_length=1)
    quality_tags: str = ""
    local_cache_path: Path
    notes: str = ""

    @model_validator(mode="after")
    def enforce_source_and_rights(self) -> "PublicWebManifestRow":
        if self.redistribution_allowed is False and self.local_file_committed:
            raise ValueError("Images without redistribution permission must not be committed")
        if not self.local_cache_path.as_posix().startswith(
            "evaluation/real_data/public_web/.local_cache/"
        ):
            raise ValueError("Public-web images must stay in the ignored local cache")
        return self

    @property
    def evaluation_ready(self) -> bool:
        return self.privacy_reviewed and self.annotation_status == "APPROVED"


class PublicWebAnnotation(StrictModel):
    sample_id: str = Field(pattern=r"^PW-\d{3}$")
    title: str | None
    event_start: str | None
    location: str | None
    deadline: str | None
    deadline_action: str | None
    expected_agent_behavior: Literal[
        "BUSINESS_COMPLETED", "SAFE_DEFERRED", "SAFE_BLOCKED",
        "RECOVERY_PENDING", "WRONG_EXECUTION", "SYSTEM_FAILED",
    ]
    ground_truth_source: Literal["OFFICIAL_PAGE_TEXT"]
    annotator: str = Field(pattern=r"^A\d{2,}$")
    reviewer: str = Field(pattern=r"^R\d{2,}$")
    ambiguity_notes: list[str] = Field(default_factory=list)


def _bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized not in {"true", "false"}:
        raise ValueError(f"{field} must be true or false")
    return normalized == "true"


def load_manifest(path: Path = DEFAULT_MANIFEST) -> list[PublicWebManifestRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != MANIFEST_FIELDS:
            raise ValueError("Public-web manifest header does not match the schema")
        raw_rows = [row for row in reader if any((v or "").strip() for v in row.values())]
    rows: list[PublicWebManifestRow] = []
    for raw in raw_rows:
        converted: dict[str, Any] = dict(raw)
        for field in ("redistribution_allowed", "privacy_reviewed", "local_file_committed"):
            converted[field] = _bool(raw[field], field)
        rows.append(PublicWebManifestRow.model_validate(converted))
    if len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("Public-web sample IDs must be unique")
    return rows


def load_candidates(path: Path = DEFAULT_CANDIDATES) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANDIDATE_FIELDS:
            raise ValueError("Public-web candidate header does not match the schema")
        return list(reader)


def validate_metadata(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
) -> tuple[list[PublicWebManifestRow], list[PublicWebAnnotation]]:
    rows = load_manifest(manifest_path)
    candidates = load_candidates(candidates_path)
    if len(candidates) < 30:
        raise ValueError("At least 30 official-source candidates are required")
    if not 15 <= len(rows) <= 20:
        raise ValueError("The selected public-web set must contain 15-20 samples")
    annotations: list[PublicWebAnnotation] = []
    for row in rows:
        path = manifest_path.parent / "annotations" / f"{row.sample_id}.json"
        if not path.is_file():
            raise ValueError(f"{row.sample_id}: annotation file is missing")
        annotation = PublicWebAnnotation.model_validate_json(path.read_text(encoding="utf-8"))
        if annotation.sample_id != row.sample_id:
            raise ValueError(f"{row.sample_id}: annotation sample ID mismatch")
        annotations.append(annotation)
    return rows, annotations


def ready_samples(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
) -> list[tuple[PublicWebManifestRow, PublicWebAnnotation]]:
    rows, annotations = validate_metadata(manifest_path, candidates_path)
    root = manifest_path.resolve().parents[3]
    pairs = []
    for row, annotation in zip(rows, annotations, strict=True):
        if not row.evaluation_ready:
            continue
        image = (root / row.local_cache_path).resolve()
        cache = (root / "evaluation/real_data/public_web/.local_cache").resolve()
        if cache not in image.parents or not image.is_file():
            raise ValueError(f"{row.sample_id}: approved sample is missing from the local cache")
        pairs.append((row, annotation))
    return pairs


def _not_executed_summary(selected: int, ready: int) -> dict[str, Any]:
    return {
        "status": "NOT_EXECUTED_LOCAL_CACHE_UNAVAILABLE",
        "selected_sample_count": selected,
        "evaluation_ready_count": ready,
        "sample_count": 0,
        "outcome_counts": {name: None for name in OUTCOMES},
        "metrics": {},
        "message": (
            "Metadata and independent page-text annotations are prepared, but formal OCR/Agent "
            "evaluation has not run because the ignored image cache and visual privacy review are incomplete."
        ),
    }


def _result_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    return "\n".join([
        "# Public-Web Real-World Notification Validation",
        "",
        "**NOT EXECUTED — LOCAL IMAGE CACHE / VISUAL PRIVACY REVIEW PENDING**",
        "",
        f"- Official-source candidates audited: {payload['candidate_count']}",
        f"- Metadata-selected samples: {summary['selected_sample_count']}",
        f"- Formally evaluated samples: {summary['sample_count']}",
        "- Images committed to Git: 0",
        "",
        "No OCR rate, Agent outcome rate, or campus-capture claim is reported. Publicly accessible "
        "does not imply redistribution permission; every selected image therefore remains outside Git.",
    ]) + "\n"


def evaluate_public_web(
    manifest_path: Path = DEFAULT_MANIFEST,
    candidates_path: Path = DEFAULT_CANDIDATES,
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    rows, _ = validate_metadata(manifest_path, candidates_path)
    candidates = load_candidates(candidates_path)
    ready = ready_samples(manifest_path, candidates_path)
    # Running the OCR/Agent path is intentionally impossible until every selected image has
    # completed the independent visual privacy review. This prevents metadata-only evidence
    # from being presented as an image evaluation.
    if ready:
        raise RuntimeError("Ready images exist; run the reviewed image-evaluation adapter before publishing metrics")
    payload = {
        "dataset": "Public-Web Real-World Notification Set",
        "source_type": "PUBLIC_WEB",
        "candidate_count": len(candidates),
        "summary": _not_executed_summary(len(rows), len(ready)),
        "results": [],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "public_web_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "public_web_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        csv.DictWriter(handle, fieldnames=("sample_id", "agent_final_classification")).writeheader()
    (output_dir / "public_web_report.md").write_text(_result_report(payload), encoding="utf-8")
    return payload


def compare_public_web_vs_synthetic(
    synthetic_path: Path = Path("outputs/evaluation/full_system_results.json"),
    public_web_path: Path = DEFAULT_OUTPUT / "public_web_results.json",
    output_dir: Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    synthetic = summarize_synthetic(synthetic_path)
    public_payload = json.loads(public_web_path.read_text(encoding="utf-8"))
    public_summary = public_payload["summary"]
    public = {
        "status": public_summary["status"],
        "sample_count": public_summary["sample_count"],
        "metrics": public_summary["metrics"],
    }
    payload = {
        "scope": "Synthetic Evaluation Set vs Public-Web Real-World Notification Set",
        "statistical_significance_claimed": False,
        "synthetic": synthetic,
        "public_web": public,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "public_web_vs_synthetic.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with (output_dir / "public_web_vs_synthetic.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("metric", "Synthetic Evaluation Set", "Public-Web Real-World Notification Set"))
        writer.writeheader()
        for metric in COMPARISON_METRICS:
            synthetic_value = synthetic["metrics"][metric]
            display = synthetic_value.get("display") if isinstance(synthetic_value, dict) else f"{synthetic_value:.3f}"
            writer.writerow({
                "metric": metric,
                "Synthetic Evaluation Set": display,
                "Public-Web Real-World Notification Set": "NOT EXECUTED",
            })
    report = "\n".join([
        "# Synthetic Evaluation Set vs Public-Web Real-World Notification Set",
        "",
        f"Synthetic Evaluation Set: N={synthetic['sample_count']}.",
        "",
        "Public-Web Real-World Notification Set: **NOT EXECUTED**.",
        "",
        "No difference, statistical significance, or real-campus generalization claim is made.",
    ]) + "\n"
    (output_dir / "public_web_vs_synthetic.md").write_text(report, encoding="utf-8")
    return payload


def main() -> int:
    payload = evaluate_public_web()
    compare_public_web_vs_synthetic()
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
