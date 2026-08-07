from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.domain.models import NoticePackageDraft, TemporalField
from glanceflow.ocr.models import OcrResult


class ExtractionIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str
    message: str
    evidence_line_ids: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    draft: NoticePackageDraft | None = None
    issues: list[ExtractionIssue] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    ambiguity_reasons: list[str] = Field(default_factory=list)
    suggested_status: SafetyGateStatus | None = None
    error_message: str | None = None
    temporal_fields: list[TemporalField] = Field(default_factory=list)


class DraftExtractor(Protocol):
    def extract(self, ocr_result: OcrResult, captured_at, timezone: str) -> ExtractionResult:
        ...
