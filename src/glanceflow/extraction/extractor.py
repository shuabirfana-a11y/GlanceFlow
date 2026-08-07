from __future__ import annotations

import re
import zlib
from datetime import datetime

from glanceflow.config import DEFAULT_TIMEZONE
from glanceflow.domain.enums import (
    DeadlineRole,
    NoticeType,
    SafetyGateStatus,
    TemporalNormalizationStatus,
    TemporalType,
)
from glanceflow.domain.models import DeadlineAction, FieldEvidence, MainEvent, NoticePackageDraft
from glanceflow.extraction.evidence_linker import EvidenceRow, group_visual_rows, validate_evidence_links
from glanceflow.extraction.normalization import find_relative_time, normalize_text, parse_datetime_texts, strip_label
from glanceflow.extraction.schemas import DraftExtractor, ExtractionIssue, ExtractionResult
from glanceflow.extraction.temporal import (
    build_temporal_field,
    classify_temporal_type,
    image_sha256,
    normalize_relative_datetime,
)
from glanceflow.ocr.models import OcrResult


_LOCATION_LABELS = ("地点", "活动地点")
_TITLE_LABELS = ("活动标题", "标题")
_ACTION_LABELS = ("截止动作", "报名动作", "申请动作")


def _field_evidence(row: EvidenceRow | None) -> FieldEvidence:
    if row is None:
        return FieldEvidence(evidence_line_ids=[], confidence=1.0)
    return FieldEvidence(evidence_line_ids=row.line_ids, confidence=row.confidence)


def _package_id(source_frame_id: str) -> str:
    leading = re.search(r"(?:^|[-_])(\d{1,4})(?:[-_]|$)", source_frame_id)
    number = int(leading.group(1)) if leading else zlib.crc32(source_frame_id.encode("utf-8")) % 10000
    return f"GF-PKG-{number % 10000:04d}"


def _find_labeled_row(rows: list[EvidenceRow], labels: tuple[str, ...]) -> tuple[EvidenceRow | None, str]:
    for row in rows:
        value = strip_label(row.text, labels)
        if value:
            return row, value
    return None, ""


class DeterministicDraftExtractor(DraftExtractor):
    version = "deterministic-v2"

    def extract(
        self,
        ocr_result: OcrResult,
        captured_at: datetime,
        timezone: str = DEFAULT_TIMEZONE,
    ) -> ExtractionResult:
        if not ocr_result.success:
            return ExtractionResult(
                success=False,
                suggested_status=SafetyGateStatus.RECAPTURE_REQUIRED,
                error_message=ocr_result.error_message or "OCR未成功。",
            )
        rows = group_visual_rows(ocr_result.evidence_lines)
        if not rows:
            return ExtractionResult(
                success=False,
                suggested_status=SafetyGateStatus.RECAPTURE_REQUIRED,
                error_message="OCR没有包含真实坐标的有效文本行。",
            )

        title_row, title = _find_labeled_row(rows, _TITLE_LABELS)
        location_row, location = _find_labeled_row(rows, _LOCATION_LABELS)
        action_row, deadline_action_text = _find_labeled_row(rows, _ACTION_LABELS)

        current_image_hash = image_sha256(ocr_result.image_path)
        if (
            ocr_result.image_sha256 is not None
            and current_image_hash is not None
            and ocr_result.image_sha256 != current_image_hash
        ):
            return ExtractionResult(
                success=False,
                suggested_status=SafetyGateStatus.RECAPTURE_REQUIRED,
                error_message="源图片内容在 OCR 后发生变化，证据哈希已失效。",
            )
        source_image_hash = current_image_hash or ocr_result.image_sha256
        temporal_fields = []
        candidates = []
        for row in rows:
            normalized_row = normalize_text(row.text)
            temporal_type = classify_temporal_type(normalized_row)
            parsed_values = parse_datetime_texts(row.text, timezone)
            if parsed_values:
                for index, parsed in enumerate(parsed_values):
                    candidate_type = temporal_type
                    if (
                        len(parsed_values) > 1
                        and "原定" in normalized_row
                        and temporal_type is TemporalType.RESCHEDULED_TIME
                        and index == 0
                    ):
                        candidate_type = TemporalType.EVENT_START
                    field = build_temporal_field(
                        row=row,
                        value=parsed[0],
                        temporal_type=candidate_type,
                        timezone=timezone,
                        relative_reference_time=None,
                        image_hash=source_image_hash,
                        ocr_version=ocr_result.provider_version,
                        extraction_rule_version=self.version,
                        normalization_status=(
                            TemporalNormalizationStatus.CANCELLED
                            if candidate_type is TemporalType.CANCELLATION_TIME
                            else None
                        ),
                    )
                    temporal_fields.append(field)
                    candidates.append((row, parsed, field))
                continue
            relative = find_relative_time(row.text)
            if relative:
                value, _ = normalize_relative_datetime(row.text, captured_at, timezone)
                field = build_temporal_field(
                    row=row,
                    value=value,
                    temporal_type=temporal_type,
                    timezone=timezone,
                    relative_reference_time=captured_at,
                    image_hash=source_image_hash,
                    ocr_version=ocr_result.provider_version,
                    extraction_rule_version=self.version,
                )
                temporal_fields.append(field)
                if value is not None:
                    candidates.append((row, (value, relative, None), field))
            elif temporal_type is TemporalType.CANCELLATION_TIME:
                temporal_fields.append(build_temporal_field(
                    row=row,
                    value=None,
                    temporal_type=temporal_type,
                    timezone=timezone,
                    relative_reference_time=None,
                    image_hash=source_image_hash,
                    ocr_version=ocr_result.provider_version,
                    extraction_rule_version=self.version,
                    normalization_status=TemporalNormalizationStatus.CANCELLED,
                ))

        cancellation_rows = [
            row
            for row in rows
            if classify_temporal_type(normalize_text(row.text)) is TemporalType.CANCELLATION_TIME
        ]
        if cancellation_rows:
            ids = [line_id for row in cancellation_rows for line_id in row.line_ids]
            return ExtractionResult(
                success=False,
                ambiguity_reasons=["通知表明活动已取消，禁止创建日历事件。"],
                issues=[ExtractionIssue(
                    issue_id="GF-EXTRACT-EVENT-CANCELLED",
                    message="检测到取消状态词；保留时间证据但禁止继续执行。",
                    evidence_line_ids=ids,
                )],
                suggested_status=SafetyGateStatus.CONTRADICTION_BLOCKED,
                temporal_fields=temporal_fields,
            )

        deadline_types = {
            TemporalType.REGISTRATION_DEADLINE,
            TemporalType.SUBMISSION_DEADLINE,
        }
        deadline_candidates = [item for item in candidates if item[2].temporal_type in deadline_types]
        deadline_rows = [row for row, _, _ in deadline_candidates]
        rescheduled = [item for item in candidates if item[2].temporal_type is TemporalType.RESCHEDULED_TIME]
        event_candidates = rescheduled or [
            item for item in candidates if item[2].temporal_type is TemporalType.EVENT_START
        ]

        if len(event_candidates) > 1 or len(deadline_candidates) > 1:
            conflicting = event_candidates if len(event_candidates) > 1 else deadline_candidates
            conflicting_ids = {item[2].evidence_id for item in conflicting}
            temporal_fields = [
                item.with_normalization_status(TemporalNormalizationStatus.CONFLICTING)
                if item.evidence_id in conflicting_ids
                else item
                for item in temporal_fields
            ]
            ids = [line_id for row, _, _ in conflicting for line_id in row.line_ids]
            return ExtractionResult(
                success=False,
                ambiguity_reasons=["发现多个同角色且无法区分的时间候选。"],
                issues=[ExtractionIssue(issue_id="GF-EXTRACT-TIME-AMBIGUOUS", message="发现多个同角色且无法区分的时间候选。", evidence_line_ids=ids)],
                suggested_status=SafetyGateStatus.CONTRADICTION_BLOCKED,
                temporal_fields=temporal_fields,
            )

        if not event_candidates:
            relative = next((find_relative_time(row.text) for row in rows if find_relative_time(row.text)), None)
            message = f"未解析时间表达：{relative}" if relative else "缺少可确定的活动日期和开始时间。"
            ids = [line_id for row in rows if relative and relative in normalize_text(row.text) for line_id in row.line_ids]
            return ExtractionResult(
                success=False,
                missing_fields=["main_event.event_start"],
                issues=[ExtractionIssue(issue_id="GF-EXTRACT-TIME-MISSING", message=message, evidence_line_ids=ids)],
                suggested_status=SafetyGateStatus.NEED_USER_INPUT,
                temporal_fields=temporal_fields,
            )

        event_row, (event_start, raw_date_text, raw_weekday_text), _ = event_candidates[0]

        # If an explicit title label is absent, use the first non-semantic row.
        if title_row is None:
            temporal_rows = [
                row
                for row in rows
                if any(field.source_text == row.text for field in temporal_fields)
            ]
            excluded = [location_row, action_row, *temporal_rows]
            for row in rows:
                if row not in excluded and not normalize_text(row.text).startswith("校园通知"):
                    title_row, title = row, normalize_text(row.text)
                    break

        deadline_action = None
        if deadline_candidates:
            deadline_row, (deadline_time, _, _), deadline_field = deadline_candidates[0]
            if deadline_field.temporal_type is TemporalType.SUBMISSION_DEADLINE:
                role = DeadlineRole.APPLICATION
            else:
                role = DeadlineRole.REGISTRATION
            deadline_action = DeadlineAction(
                deadline=deadline_time,
                action=deadline_action_text,
                role=role,
                deadline_evidence=_field_evidence(deadline_row),
                action_evidence=_field_evidence(action_row),
            )

        all_links = []
        for row in (title_row, event_row, location_row, action_row, *deadline_rows):
            if row is not None:
                all_links.extend(row.line_ids)
        if all_links and not validate_evidence_links(ocr_result, all_links):
            return ExtractionResult(
                success=False,
                suggested_status=SafetyGateStatus.RECAPTURE_REQUIRED,
                error_message="抽取器检测到不属于当前 OCR 结果的证据引用。",
            )

        draft = NoticePackageDraft(
            notice_package_id=_package_id(ocr_result.source_frame_id),
            notice_type=NoticeType.EVENT_WITH_DEADLINE if deadline_action else NoticeType.EVENT_NOTICE,
            captured_at=captured_at,
            timezone=timezone,
            source_frame_id=ocr_result.source_frame_id,
            main_event=MainEvent(
                title=title,
                event_start=event_start,
                location=location,
                title_evidence=_field_evidence(title_row),
                time_evidence=_field_evidence(event_row),
                location_evidence=_field_evidence(location_row),
                raw_date_text=raw_date_text,
                raw_weekday_text=raw_weekday_text,
            ),
            deadline_action=deadline_action,
            evidence_lines=ocr_result.evidence_lines,
            temporal_fields=temporal_fields,
            extraction_version=self.version,
            source_image_path=(
                ocr_result.image_path if ocr_result.image_path.is_file() else None
            ),
            metadata={
                "ocr_provider": ocr_result.provider_name,
                "ocr_provider_version": ocr_result.provider_version,
            },
        )
        return ExtractionResult(success=True, draft=draft, temporal_fields=temporal_fields)
