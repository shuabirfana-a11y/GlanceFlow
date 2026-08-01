from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from glanceflow.config import DEFAULT_TIMEZONE
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.domain.models import NoticePackageDraft
from glanceflow.extraction.extractor import DeterministicDraftExtractor, DraftExtractor
from glanceflow.extraction.schemas import ExtractionResult
from glanceflow.ocr.base import OcrProvider
from glanceflow.ocr.models import ImageQualityResult, OcrResult
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.ocr.quality import add_ocr_text_check, inspect_image_quality
from glanceflow.safety.gate import evaluate_notice
from glanceflow.safety.results import SafetyGateDecision


class ImagePipelineResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_path: Path
    source_frame_id: str
    quality_result: ImageQualityResult
    ocr_result: OcrResult | None = None
    extraction_result: ExtractionResult | None = None
    safety_decision: SafetyGateDecision | None = None
    final_status: SafetyGateStatus
    can_proceed_to_confirmation: bool
    reasons: list[str] = Field(default_factory=list)


def source_frame_id_for(path: Path) -> str:
    # Python's Unicode-aware \w preserves Chinese names while removing path
    # punctuation, avoiding collisions such as every Chinese file -> image.
    safe = re.sub(r"[^\w-]+", "-", path.stem, flags=re.UNICODE).strip("-_") or "image"
    return f"frame-{safe}"


def process_image(
    image_path: Path,
    captured_at: datetime,
    timezone: str = DEFAULT_TIMEZONE,
    *,
    provider: OcrProvider | None = None,
    extractor: DraftExtractor | None = None,
    existing_drafts: list[NoticePackageDraft] | None = None,
) -> ImagePipelineResult:
    path = Path(image_path)
    source_frame_id = source_frame_id_for(path)
    quality = inspect_image_quality(path)
    if not quality.passed:
        return ImagePipelineResult(
            image_path=path,
            source_frame_id=source_frame_id,
            quality_result=quality,
            final_status=SafetyGateStatus.RECAPTURE_REQUIRED,
            can_proceed_to_confirmation=False,
            reasons=quality.rejection_reasons,
        )

    ocr = (provider or RapidOcrProvider()).recognize(path, source_frame_id)
    if not ocr.success:
        return ImagePipelineResult(
            image_path=path,
            source_frame_id=source_frame_id,
            quality_result=quality,
            ocr_result=ocr,
            final_status=SafetyGateStatus.RECAPTURE_REQUIRED,
            can_proceed_to_confirmation=False,
            reasons=[ocr.error_message or "OCR识别失败。"],
        )

    quality = add_ocr_text_check(quality, [line.text for line in ocr.evidence_lines])
    if not quality.passed:
        return ImagePipelineResult(
            image_path=path,
            source_frame_id=source_frame_id,
            quality_result=quality,
            ocr_result=ocr,
            final_status=SafetyGateStatus.RECAPTURE_REQUIRED,
            can_proceed_to_confirmation=False,
            reasons=quality.rejection_reasons,
        )

    extraction = (extractor or DeterministicDraftExtractor()).extract(ocr, captured_at, timezone)
    if not extraction.success or extraction.draft is None:
        status = extraction.suggested_status or SafetyGateStatus.NEED_USER_INPUT
        reasons = [issue.message for issue in extraction.issues]
        reasons.extend(extraction.ambiguity_reasons)
        if extraction.error_message:
            reasons.append(extraction.error_message)
        return ImagePipelineResult(
            image_path=path,
            source_frame_id=source_frame_id,
            quality_result=quality,
            ocr_result=ocr,
            extraction_result=extraction,
            final_status=status,
            can_proceed_to_confirmation=False,
            reasons=list(dict.fromkeys(reasons)),
        )

    decision = evaluate_notice(extraction.draft, existing_drafts)
    reasons = decision.blocking_reasons + decision.required_user_inputs + decision.recapture_reasons
    return ImagePipelineResult(
        image_path=path,
        source_frame_id=source_frame_id,
        quality_result=quality,
        ocr_result=ocr,
        extraction_result=extraction,
        safety_decision=decision,
        final_status=decision.status,
        can_proceed_to_confirmation=decision.can_proceed_to_confirmation,
        reasons=reasons,
    )
