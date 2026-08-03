from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

import glanceflow.evaluation.stage8 as stage8_module
from glanceflow.evaluation.privacy import assert_public_payload_safe, redact_sensitive_text
from glanceflow.evaluation.real_comparison import compare_real_vs_synthetic
from glanceflow.evaluation.real_data import (
    MANIFEST_FIELDS,
    OUTCOMES,
    RealManifestRow,
    build_decision_traces,
    evaluate_real_data,
    fraction,
    load_real_manifest,
    summarize_results,
    validate_real_dataset,
)
from glanceflow.evaluation.stage8 import run_stage8
from glanceflow.evaluation.user_study import REQUIRED_FIELDS, analyze, run_user_study_analysis


def _manifest_row(**updates):
    row = {
        "sample_id": "RD-001", "source_type": "REAL_CAMPUS_CAPTURE", "capture_context": "permitted campus board",
        "permission_confirmed": True, "privacy_reviewed": True, "sanitized": True,
        "annotation_status": "APPROVED", "annotator_id": "A01", "reviewer_id": "R01",
        "contains_event": True, "contains_deadline": False,
        "image_path": "evaluation/real_data/sanitized/RD-001.png", "notes": "",
    }
    row.update(updates)
    return row


def _write_empty_manifest(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS).writeheader()


def _write_user_csv(path: Path, rows: list[dict] | None = None) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_FIELDS)
        writer.writeheader()
        writer.writerows(rows or [])


def _user_row(**updates):
    row = {
        "participant_id": "P01", "session_date": "2026-08-03", "task_id": "T1",
        "completed": "true", "completion_time_seconds": "42.5", "confirmation_count": "1",
        "clarification_count": "0", "recapture_count": "0", "incorrect_action": "false",
        "hud_understood": "5", "trust_rating": "4", "burden_rating": "2",
        "continue_use_rating": "4", "free_comment": "clear", "agent_final_classification": "BUSINESS_COMPLETED",
        "calendar_result": "VERIFIED", "recovery_required": "false", "observer_note": "none",
    }
    row.update(updates)
    return row


def test_real_manifest_schema_accepts_only_rd_ids():
    assert RealManifestRow.model_validate(_manifest_row()).sample_id == "RD-001"
    with pytest.raises(ValidationError):
        RealManifestRow.model_validate(_manifest_row(sample_id="GF-EVAL-001"))


def test_real_and_synthetic_sources_cannot_be_mixed():
    with pytest.raises(ValidationError, match="Synthetic samples"):
        RealManifestRow.model_validate(_manifest_row(source_type="SYNTHETIC"))


@pytest.mark.parametrize("field", ["permission_confirmed", "privacy_reviewed", "sanitized"])
def test_real_samples_require_permission_privacy_and_sanitization(field):
    with pytest.raises(ValidationError):
        RealManifestRow.model_validate(_manifest_row(**{field: False}))


def test_empty_real_manifest_reports_not_executed(tmp_path):
    manifest = tmp_path / "evaluation/real_data/manifest.csv"
    _write_empty_manifest(manifest)
    output = tmp_path / "outputs"
    payload = evaluate_real_data(manifest, output)
    assert payload["summary"]["status"] == "NOT_EXECUTED"
    assert payload["summary"]["outcome_counts"] == {name: None for name in OUTCOMES}
    assert "NOT EXECUTED" in (output / "real_data_report.md").read_text(encoding="utf-8")


def test_manifest_rejects_missing_sanitized_file(tmp_path):
    manifest = tmp_path / "evaluation/real_data/manifest.csv"
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerow({key: str(value).lower() if isinstance(value, bool) else value for key, value in _manifest_row().items()})
    with pytest.raises(ValueError, match="sanitized image"):
        validate_real_dataset(manifest)


def test_empty_real_outputs_have_consistent_json_csv_markdown(tmp_path):
    manifest = tmp_path / "evaluation/real_data/manifest.csv"
    _write_empty_manifest(manifest)
    output = tmp_path / "out"
    evaluate_real_data(manifest, output)
    payload = json.loads((output / "real_data_results.json").read_text(encoding="utf-8"))
    with (output / "real_data_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
    assert payload["summary"]["sample_count"] == 0
    assert "尚未采集真实校园素材" in (output / "real_data_report.md").read_text(encoding="utf-8")


def test_fraction_always_keeps_numerator_and_denominator():
    assert fraction(3, 4)["display"] == "3/4 (75.0%)"
    assert fraction(0, 0)["display"] == "NOT EXECUTED"


def test_six_classification_counts_sum_to_sample_count():
    rows = []
    for outcome in OUTCOMES:
        row = {"agent_final_classification": outcome, "ocr_success": True, "recapture_requested": False,
               "clarification_count": 0, "confirmation_count": 0, "confirmation_bypass": 0,
               "duplicate_execution": 0, "unsafe_tool_calls": 0, "latency_ms": 1.0}
        for field in ("title", "event_time", "location", "deadline"):
            row[f"expected_{field}"] = None
            row[f"predicted_{field}"] = None
        rows.append(row)
    summary = summarize_results(rows)
    assert sum(summary["outcome_counts"].values()) == summary["sample_count"] == 6
    assert summary["target_met"] is False


def test_decision_trace_preserves_real_sample_id_without_ocr_text():
    row = {
        "sample_id": "RD-007", "agent_final_classification": "SAFE_DEFERRED",
        "ocr_success": False, "input_type": "IMAGE", "expected_behavior": "SAFE_DEFERRED",
        "final_reason": "recapture", "confirmation_count": 0, "business_completed": False,
        "recapture_requested": True, "wrong_execution": False, "system_failed": False,
    }
    trace = build_decision_traces([row])[0]
    assert trace["sample_id"] == "RD-007"
    assert set(("Observe", "Risk", "Decision", "Tool", "Result", "Verify")) <= set(trace)
    assert "ocr_lines" not in json.dumps(trace)


def test_privacy_patterns_are_redacted_or_blocked():
    assert redact_sensitive_text("邮箱 user@example.com") == "邮箱 [REDACTED]"
    with pytest.raises(ValueError, match="prohibited privacy"):
        assert_public_payload_safe({"note": "手机号：13800138000"})


def test_empty_user_study_does_not_invent_rates_or_participants(tmp_path):
    records = tmp_path / "records.csv"
    _write_user_csv(records)
    result = analyze(records)
    assert result["message"] == "尚未执行真人用户实验。"
    assert result["participants"] == 0 and result["results_available"] is False
    assert "completion_rate" not in result


def test_user_task_rows_are_complete_and_keep_n(tmp_path):
    records = tmp_path / "records.csv"
    _write_user_csv(records, [_user_row(), _user_row(task_id="T2", completed="false")])
    result = analyze(records)
    assert result["participants"] == 1 and result["total_tasks"] == 2
    assert result["protocol_complete"] is False
    assert result["completion_rate"]["display"] == "1/2 (50.0%)"
    assert result["ratings"]["trust_rating"]["n"] == 2


def test_user_analysis_rejects_nonanonymous_participant(tmp_path):
    records = tmp_path / "records.csv"
    _write_user_csv(records, [_user_row(participant_id="Alice")])
    with pytest.raises(ValueError, match="anonymous IDs"):
        analyze(records)


def test_user_public_outputs_redact_privacy_fields(tmp_path):
    records = tmp_path / "records.csv"
    _write_user_csv(records, [_user_row(free_comment="联系 user@example.com")])
    output = tmp_path / "out"
    run_user_study_analysis(records, output)
    text = (output / "user_study_results.csv").read_text(encoding="utf-8-sig")
    assert "user@example.com" not in text and "[REDACTED]" in text


def test_real_vs_synthetic_keeps_sources_separate(tmp_path):
    real = tmp_path / "real.json"
    real.write_text(json.dumps({"summary": {"status": "NOT_EXECUTED", "sample_count": 0}, "results": []}), encoding="utf-8")
    result = compare_real_vs_synthetic(real_path=real, output_dir=tmp_path / "out")
    assert result["synthetic"]["sample_count"] == 46
    assert result["real"]["sample_count"] == 0
    assert result["statistical_significance_claimed"] is False


def test_stage8_reports_absent_experiments_as_not_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(stage8_module, "HANDOFF", tmp_path / "stage8-handoff.md")
    monkeypatch.setattr(stage8_module, "FAILURES", tmp_path / "stage8-failures.md")
    monkeypatch.setattr(stage8_module, "STATUS", tmp_path / "stage8-status.json")
    status = run_stage8(full_test_result="TEST RUN")
    assert status["real_data_status"] == status["user_study_status"] == "NOT EXECUTED"
    handoff = stage8_module.HANDOFF.read_text(encoding="utf-8")
    failure = stage8_module.FAILURES.read_text(encoding="utf-8")
    assert handoff.count("## ") == 20
    assert "NOT EXECUTED" in failure
