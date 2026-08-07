from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .real_world_preflight import DEFAULT_MANIFEST, SourceType, load_manifest, run_preflight


OUTPUT = Path("outputs/real_world")
METRICS = (
    "ocr_character_accuracy", "field_exact_match", "temporal_role_accuracy",
    "temporal_exact_match", "location_exact_match", "evidence_completeness",
    "safety_decision_accuracy", "executable_recall", "unsafe_execution_rate",
    "false_block_rate", "clarification_rate", "recapture_rate", "end_to_end_success",
)
FAILURES = (
    "PERCEPTION_ERROR", "OCR_ERROR", "FIELD_EXTRACTION_ERROR", "TEMPORAL_ROLE_ERROR",
    "TEMPORAL_NORMALIZATION_ERROR", "EVIDENCE_BINDING_ERROR", "SAFETY_FALSE_BLOCK",
    "SAFETY_FALSE_ALLOW", "AGENT_DECISION_ERROR", "TRANSACTION_ERROR",
)


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evaluate(manifest_path: Path = DEFAULT_MANIFEST, output_dir: Path = OUTPUT) -> dict[str, Any]:
    preflight = run_preflight(manifest_path, output_dir / "preflight.json")
    rows = load_manifest(manifest_path)
    real_ids = [r.sample_id for r in rows if r.source_type in {SourceType.REAL_CAMPUS_LOCAL, SourceType.REAL_CAMPUS_PUBLIC}]
    metric_rows = [{"metric": name, "numerator": "", "denominator": 0, "sample_ids": "", "value": "NOT_EVALUATED"} for name in METRICS]
    summary = {
        **preflight,
        "status_reason": "No permitted, independently annotated real campus samples are available." if not real_ids else "Evaluation runner requires frozen-pipeline sample execution.",
        "metrics": {r["metric"]: {"numerator": None, "denominator": 0, "sample_ids": [], "value": None} for r in metric_rows},
        "failure_taxonomy": list(FAILURES),
        "rapidocr_vs_paddleocr": {"status": "NOT_EVALUATED", "reason": "Comparison starts only after the first real-campus dataset is available."},
        "real_calendar_writes": 0,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "figures").mkdir(exist_ok=True)
    (output_dir / "real_world_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / "sample_results.csv", ["sample_id", "source_type", "status", "wrong_execution", "failure_layer"], [])
    _write_csv(output_dir / "field_metrics.csv", ["metric", "numerator", "denominator", "sample_ids", "value"], metric_rows)
    _write_csv(output_dir / "failure_analysis.csv", ["sample_id", "failure_layer", "detail"], [])
    _write_csv(output_dir / "vision_degradation.csv", ["sample_id", "condition", "ocr_correct", "evidence_complete", "safety_correct", "recapture", "final_result"], [])
    _write_csv(output_dir / "ocr_comparison.csv", ["sample_id", "adapter", "status", "character_accuracy", "temporal_accuracy", "evidence_completeness", "bbox_available", "confidence_available", "latency_ms", "p90_ms", "memory_mb", "startup_ms", "installation_notes"], [])
    return summary


def main() -> int:
    result = evaluate()
    print(f"REAL_CAMPUS_SAMPLE_COUNT={result['REAL_CAMPUS_SAMPLE_COUNT']}")
    print(f"STATUS={result['STATUS']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
