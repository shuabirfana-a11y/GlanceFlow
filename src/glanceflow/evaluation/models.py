from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.domain.enums import NoticeType, SafetyGateStatus


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MediaType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class SourceType(StrEnum):
    ARTIFICIAL_POSTER = "ARTIFICIAL_POSTER"
    ARTIFICIAL_FIRST_PERSON_VIDEO = "ARTIFICIAL_FIRST_PERSON_VIDEO"
    TEAM_CAPTURE = "TEAM_CAPTURE"
    PUBLIC_WEB = "PUBLIC_WEB"


class EvaluationAnnotation(EvaluationModel):
    sample_id: str = Field(pattern=r"^GF-EVAL-\d{3}$")
    input_path: Path
    media_type: MediaType
    source_type: SourceType
    category: str
    expected_notice_type: NoticeType
    expected_title: str | None
    expected_event_start: str | None
    expected_location: str | None
    expected_deadline: str | None
    expected_safety_status: SafetyGateStatus
    expected_failure_reason: str | None
    is_executable: bool
    scenario_tags: list[str] = Field(min_length=1)
    synthetic: bool
    annotation_notes: str
    existing_context: Literal["NONE", "DUPLICATE", "CONFLICT"] = "NONE"
    fault_plan: Literal["NONE", "READBACK_MISMATCH", "SECOND_CREATE_FAILURE"] = "NONE"


class DatasetManifest(EvaluationModel):
    dataset_id: str
    version: str
    generated_with_seed: int
    captured_at: str
    simulator_environment: str
    contains_team_capture: bool
    consent_records_required: bool
    sample_count: int
    category_counts: dict[str, int]
    samples: list[EvaluationAnnotation]

    @model_validator(mode="after")
    def counts_match_samples(self) -> "DatasetManifest":
        if self.sample_count != len(self.samples):
            raise ValueError("sample_count must match samples")
        observed: dict[str, int] = {}
        for sample in self.samples:
            observed[sample.category] = observed.get(sample.category, 0) + 1
        if observed != self.category_counts:
            raise ValueError("category_counts must match samples")
        if len({sample.sample_id for sample in self.samples}) != len(self.samples):
            raise ValueError("sample_id values must be unique")
        return self


class StageLatencies(EvaluationModel):
    frame_capture_ms: float = 0
    frame_selection_ms: float = 0
    ocr_ms: float = 0
    extraction_ms: float = 0
    safety_gate_ms: float = 0
    calendar_transaction_ms: float = 0
    total_ms: float = 0


class SystemResult(EvaluationModel):
    sample_id: str
    system_id: str
    predicted_safety_status: SafetyGateStatus
    executed: bool
    active_event_count: int = 0
    actual_title: str | None = None
    actual_event_start: str | None = None
    actual_location: str | None = None
    actual_deadline: str | None = None
    fields_match: bool = False
    correct_execution: bool = False
    erroneous_execution: bool = False
    false_rejection: bool = False
    package_completely_correct: bool = False
    readback_verified: bool | None = None
    rollback_attempted: bool = False
    rollback_succeeded: bool | None = None
    duplicate_detected: bool | None = None
    conflict_detected: bool | None = None
    transaction_status: str | None = None
    failure_layer: str | None = None
    failure_reasons: list[str] = Field(default_factory=list)
    ocr_lines: list[dict[str, Any]] = Field(default_factory=list)
    extracted_fields: dict[str, Any] | None = None
    latencies: StageLatencies


class MetricValue(EvaluationModel):
    value: float | None
    numerator: int
    denominator: int
    display: str


class SystemMetrics(EvaluationModel):
    system_id: str
    sample_count: int
    erroneous_execution_rate: MetricValue
    valid_coverage_rate: MetricValue
    false_rejection_rate: MetricValue
    package_complete_accuracy: MetricValue
    safety_macro_f1: float
    per_class: dict[str, dict[str, float | int]]
    confusion_matrix: dict[str, dict[str, int]]
    failure_case_count: int
