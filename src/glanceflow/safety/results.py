from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from glanceflow.domain.enums import SafetyGateStatus, ValidationSeverity


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    passed: bool
    severity: ValidationSeverity
    message: str
    affected_fields: list[str] = Field(default_factory=list)
    evidence_line_ids: list[str] = Field(default_factory=list)
    suggested_action: str | None = None


class SafetyGateDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: SafetyGateStatus
    can_proceed_to_confirmation: bool
    rule_results: list[ValidationResult]
    blocking_reasons: list[str] = Field(default_factory=list)
    required_user_inputs: list[str] = Field(default_factory=list)
    recapture_reasons: list[str] = Field(default_factory=list)
    summary: str
    draft_snapshot: dict[str, Any]

