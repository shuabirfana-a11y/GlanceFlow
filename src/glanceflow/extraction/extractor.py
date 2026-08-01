from __future__ import annotations

import re
import zlib
from datetime import datetime

from glanceflow.config import DEFAULT_TIMEZONE
from glanceflow.domain.enums import DeadlineRole, NoticeType, SafetyGateStatus
from glanceflow.domain.models import DeadlineAction, FieldEvidence, MainEvent, NoticePackageDraft
from glanceflow.extraction.evidence_linker import EvidenceRow, group_visual_rows, validate_evidence_links
from glanceflow.extraction.normalization import find_relative_time, normalize_text, parse_datetime_text, strip_label
from glanceflow.extraction.schemas import DraftExtractor, ExtractionIssue, ExtractionResult
from glanceflow.ocr.models import OcrResult


_DEADLINE_WORDS = ("报名截止", "申请截止")
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
    version = "deterministic-v1"

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

        deadline_rows = [row for row in rows if any(word in normalize_text(row.text) for word in _DEADLINE_WORDS)]
        deadline_candidates = [(row, parse_datetime_text(row.text, timezone)) for row in deadline_rows]
        deadline_candidates = [(row, parsed) for row, parsed in deadline_candidates if parsed is not None]

        event_candidates = []
        for row in rows:
            if row in deadline_rows:
                continue
            parsed = parse_datetime_text(row.text, timezone)
            if parsed is not None:
                event_candidates.append((row, parsed))

        if len(event_candidates) > 1:
            ids = [line_id for row, _ in event_candidates for line_id in row.line_ids]
            return ExtractionResult(
                success=False,
                ambiguity_reasons=["发现多个无法区分的活动日期时间。"],
                issues=[ExtractionIssue(issue_id="GF-EXTRACT-TIME-AMBIGUOUS", message="发现多个无法区分的活动日期时间。", evidence_line_ids=ids)],
                suggested_status=SafetyGateStatus.CONTRADICTION_BLOCKED,
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
            )

        event_row, (event_start, raw_date_text, raw_weekday_text) = event_candidates[0]

        # If an explicit title label is absent, use the first non-semantic row.
        if title_row is None:
            excluded = [event_row, location_row, action_row, *deadline_rows]
            for row in rows:
                if row not in excluded and not normalize_text(row.text).startswith("校园通知"):
                    title_row, title = row, normalize_text(row.text)
                    break

        deadline_action = None
        if deadline_candidates:
            deadline_row, (deadline_time, _, _) = deadline_candidates[0]
            deadline_text = normalize_text(deadline_row.text)
            role = DeadlineRole.APPLICATION if "申请截止" in deadline_text else DeadlineRole.REGISTRATION
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
            extraction_version=self.version,
            metadata={
                "ocr_provider": ocr_result.provider_name,
                "ocr_provider_version": ocr_result.provider_version,
                "source_image": str(ocr_result.image_path),
            },
        )
        return ExtractionResult(success=True, draft=draft)
