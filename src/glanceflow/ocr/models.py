import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from glanceflow.domain.models import EvidenceLine


class OcrModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QualityCheckResult(OcrModel):
    check_id: str
    passed: bool
    message: str
    measured_value: float | int | str | None = None
    threshold: float | int | str | None = None


class ImageQualityResult(OcrModel):
    passed: bool
    image_path: Path
    image_width: int | None = None
    image_height: int | None = None
    checks: list[QualityCheckResult] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)


class OcrResult(OcrModel):
    source_frame_id: str
    image_path: Path
    image_width: int
    image_height: int
    image_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    evidence_lines: list[EvidenceLine] = Field(default_factory=list)
    provider_name: str
    provider_version: str
    processing_time_ms: float
    warnings: list[str] = Field(default_factory=list)
    success: bool
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_evidence_invariants(self) -> "OcrResult":
        line_ids = [line.line_id for line in self.evidence_lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("OCR evidence line_id values must be unique")
        for line in self.evidence_lines:
            if line.source_frame_id != self.source_frame_id:
                raise ValueError("OCR evidence source_frame_id must match the result")
            if line.bbox is None:
                raise ValueError("OCR evidence bbox must contain real coordinates")
            x1, y1, x2, y2 = line.bbox
            if not (0 <= x1 <= x2 <= self.image_width and 0 <= y1 <= y2 <= self.image_height):
                raise ValueError("OCR evidence bbox must stay within image bounds")
        if self.image_sha256 is not None and self.image_path.is_file():
            actual = hashlib.sha256(self.image_path.read_bytes()).hexdigest()
            if actual != self.image_sha256:
                raise ValueError("OCR image_sha256 must match the source image")
        return self
