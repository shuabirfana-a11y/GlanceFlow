from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime

from glanceflow.config import CORE_EVIDENCE_MIN_CONFIDENCE
from glanceflow.domain.enums import NoticeType, ValidationSeverity
from glanceflow.domain.models import FieldEvidence, NoticePackageDraft
from glanceflow.safety.results import ValidationResult


def _result(
    rule_id: str,
    passed: bool,
    message: str,
    *,
    severity: ValidationSeverity = ValidationSeverity.INFO,
    fields: Iterable[str] = (),
    evidence: Iterable[str] = (),
    action: str | None = None,
) -> ValidationResult:
    return ValidationResult(
        rule_id=rule_id,
        passed=passed,
        severity=ValidationSeverity.INFO if passed else severity,
        message=message,
        affected_fields=list(fields),
        evidence_line_ids=list(dict.fromkeys(evidence)),
        suggested_action=None if passed else action,
    )


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _core_evidence(draft: NoticePackageDraft) -> list[tuple[str, FieldEvidence]]:
    event = draft.main_event
    items = [
        ("main_event.title", event.title_evidence),
        ("main_event.event_start", event.time_evidence),
        ("main_event.location", event.location_evidence),
    ]
    if draft.deadline_action is not None:
        items.extend(
            [
                ("deadline_action.deadline", draft.deadline_action.deadline_evidence),
                ("deadline_action.action", draft.deadline_action.action_evidence),
            ]
        )
    return items


def rule_field_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    passed = bool(draft.main_event.title.strip())
    return _result(
        "GF-FIELD-001",
        passed,
        "活动标题完整。" if passed else "活动标题缺失。",
        severity=ValidationSeverity.WARNING,
        fields=["main_event.title"],
        action="请补充活动标题。",
    )


def rule_field_002(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    passed = bool(draft.main_event.location.strip())
    return _result(
        "GF-FIELD-002",
        passed,
        "活动地点完整。" if passed else "活动地点缺失。",
        severity=ValidationSeverity.WARNING,
        fields=["main_event.location"],
        action="请补充活动地点。",
    )


def rule_time_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    passed = _is_aware(draft.captured_at)
    return _result(
        "GF-TIME-001",
        passed,
        "采集时间包含时区。" if passed else "采集时间缺少时区，无法确定时间基准。",
        severity=ValidationSeverity.BLOCKING,
        fields=["captured_at"],
        action="使用带时区的采集时间重新生成草案。",
    )


def rule_time_002(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    passed = _is_aware(draft.main_event.event_start)
    return _result(
        "GF-TIME-002",
        passed,
        "活动时间包含时区。" if passed else "活动时间缺少时区。",
        severity=ValidationSeverity.BLOCKING,
        fields=["main_event.event_start"],
        action="明确活动时间的时区。",
    )


def rule_time_003(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    comparable = _is_aware(draft.captured_at) and _is_aware(draft.main_event.event_start)
    passed = comparable and draft.main_event.event_start > draft.captured_at
    message = "活动时间晚于采集时间。" if passed else "活动时间已过期或无法安全比较。"
    return _result(
        "GF-TIME-003",
        passed,
        message,
        severity=ValidationSeverity.BLOCKING,
        fields=["captured_at", "main_event.event_start"],
        action="核对通知是否仍然有效以及活动时间。",
    )


_WEEKDAYS = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
    "6": 5,
    "7": 6,
}


def _parse_raw_date(text: str) -> date | None:
    normalized = text.strip()
    match = re.search(r"(\d{4})\s*[年\-/]\s*(\d{1,2})\s*[月\-/]\s*(\d{1,2})\s*日?", normalized)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _parse_weekday(text: str) -> int | None:
    match = re.search(r"(?:星期|周)\s*([一二三四五六日天1-7])", text.strip())
    return _WEEKDAYS.get(match.group(1)) if match else None


def rule_time_004(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    raw_date = draft.main_event.raw_date_text
    raw_weekday = draft.main_event.raw_weekday_text
    if not raw_date or not raw_weekday:
        return _result("GF-TIME-004", True, "未同时提供原始日期和星期，无需一致性检查。")
    parsed_date = _parse_raw_date(raw_date)
    parsed_weekday = _parse_weekday(raw_weekday)
    passed = (
        parsed_date is not None
        and parsed_weekday is not None
        and parsed_date.weekday() == parsed_weekday
        and parsed_date == draft.main_event.event_start.date()
    )
    return _result(
        "GF-TIME-004",
        passed,
        "原始日期、星期与活动时间一致。" if passed else "原始日期、星期或结构化活动日期不一致。",
        severity=ValidationSeverity.BLOCKING,
        fields=["main_event.raw_date_text", "main_event.raw_weekday_text", "main_event.event_start"],
        evidence=draft.main_event.time_evidence.evidence_line_ids,
        action="禁止自动猜测，请人工核对原通知日期和星期。",
    )


def rule_time_005(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    expression = (draft.main_event.unresolved_time_expression or "").strip()
    passed = not expression
    return _result(
        "GF-TIME-005",
        passed,
        "不存在未解析时间表达。" if passed else f"存在未解析时间表达：{expression}",
        severity=ValidationSeverity.WARNING,
        fields=["main_event.unresolved_time_expression"],
        evidence=draft.main_event.time_evidence.evidence_line_ids,
        action="请明确活动的具体日期和时间。",
    )


def rule_deadline_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    if draft.notice_type is not NoticeType.EVENT_WITH_DEADLINE:
        return _result("GF-DEADLINE-001", True, "通知类型不要求截止事项。")
    deadline = draft.deadline_action
    passed = bool(
        deadline is not None
        and deadline.action.strip()
        and deadline.role
        and deadline.deadline_evidence.evidence_line_ids
        and deadline.action_evidence.evidence_line_ids
    )
    evidence = []
    if deadline is not None:
        evidence = deadline.deadline_evidence.evidence_line_ids + deadline.action_evidence.evidence_line_ids
    return _result(
        "GF-DEADLINE-001",
        passed,
        "截止事项字段与证据完整。" if passed else "截止事项的时间、动作、角色或证据不完整。",
        severity=ValidationSeverity.WARNING,
        fields=["deadline_action"],
        evidence=evidence,
        action="请补充完整的截止事项及其证据。",
    )


def rule_deadline_002(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    deadline = draft.deadline_action
    if deadline is None:
        return _result("GF-DEADLINE-002", True, "不存在需要排序校验的截止时间。")
    passed = deadline.deadline < draft.main_event.event_start
    return _result(
        "GF-DEADLINE-002",
        passed,
        "截止时间早于活动开始时间。" if passed else "截止时间不早于活动开始时间。",
        severity=ValidationSeverity.BLOCKING,
        fields=["deadline_action.deadline", "main_event.event_start"],
        evidence=deadline.deadline_evidence.evidence_line_ids,
        action="核对截止时间；本阶段不自动应用签到或入场例外。",
    )


def rule_evidence_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    missing = [field for field, evidence in _core_evidence(draft) if not evidence.evidence_line_ids]
    passed = not missing
    return _result(
        "GF-EVIDENCE-001",
        passed,
        "所有核心字段均绑定证据行。" if passed else "存在未绑定证据行的核心字段。",
        severity=ValidationSeverity.WARNING,
        fields=missing,
        action="为缺失字段补充可追溯的证据行。",
    )


def rule_evidence_002(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    known = {line.line_id for line in draft.evidence_lines}
    cited = [(field, line_id) for field, item in _core_evidence(draft) for line_id in item.evidence_line_ids]
    invalid = [(field, line_id) for field, line_id in cited if line_id not in known]
    passed = not invalid
    return _result(
        "GF-EVIDENCE-002",
        passed,
        "所有引用的证据行均真实存在。" if passed else "存在引用但不在证据集合中的 line_id。",
        severity=ValidationSeverity.ERROR,
        fields=[field for field, _ in invalid],
        evidence=[line_id for _, line_id in invalid],
        action="重新采集或修复证据引用。",
    )


def rule_evidence_003(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    known = {line.line_id: line for line in draft.evidence_lines}
    mismatches = [
        (field, line_id)
        for field, item in _core_evidence(draft)
        for line_id in item.evidence_line_ids
        if line_id in known and known[line_id].source_frame_id != draft.source_frame_id
    ]
    passed = not mismatches
    return _result(
        "GF-EVIDENCE-003",
        passed,
        "核心证据均来自当前源帧。" if passed else "核心证据包含来自其他源帧的内容。",
        severity=ValidationSeverity.ERROR,
        fields=[field for field, _ in mismatches],
        evidence=[line_id for _, line_id in mismatches],
        action="重新采集当前通知并仅绑定当前源帧证据。",
    )


def rule_confidence_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    known = {line.line_id: line for line in draft.evidence_lines}
    low: list[tuple[str, str]] = []
    for field, item in _core_evidence(draft):
        if item.confidence < CORE_EVIDENCE_MIN_CONFIDENCE:
            low.append((field, "字段置信度"))
        for line_id in item.evidence_line_ids:
            line = known.get(line_id)
            if line is not None and line.confidence < CORE_EVIDENCE_MIN_CONFIDENCE:
                low.append((field, line_id))
    passed = not low
    return _result(
        "GF-CONFIDENCE-001",
        passed,
        "所有核心证据置信度达到阈值。" if passed else f"核心证据置信度低于 {CORE_EVIDENCE_MIN_CONFIDENCE:.2f}。",
        severity=ValidationSeverity.ERROR,
        fields=[field for field, _ in low],
        evidence=[item for _, item in low if item != "字段置信度"],
        action="请靠近通知并重新采集清晰画面。",
    )


def rule_notice_001(draft: NoticePackageDraft, _: list[NoticePackageDraft]) -> ValidationResult:
    has_deadline = draft.deadline_action is not None
    passed = (
        draft.notice_type is NoticeType.EVENT_WITH_DEADLINE and has_deadline
    ) or (
        draft.notice_type is NoticeType.EVENT_NOTICE and not has_deadline
    )
    return _result(
        "GF-NOTICE-001",
        passed,
        "通知类型与字段组合一致。" if passed else "通知类型与截止事项字段组合不一致。",
        severity=ValidationSeverity.BLOCKING,
        fields=["notice_type", "deadline_action"],
        action="修正通知类型或截止事项字段，禁止自动猜测。",
    )


def _normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def rule_duplicate_001(draft: NoticePackageDraft, existing: list[NoticePackageDraft]) -> ValidationResult:
    title = _normalize_title(draft.main_event.title)
    duplicates = [
        item.notice_package_id
        for item in existing
        if item.notice_package_id != draft.notice_package_id
        and _normalize_title(item.main_event.title) == title
        and item.main_event.event_start == draft.main_event.event_start
    ]
    passed = not duplicates
    return _result(
        "GF-DUPLICATE-001",
        passed,
        "未发现标题与开始时间均相同的通知。" if passed else f"疑似重复通知：{', '.join(duplicates)}",
        severity=ValidationSeverity.BLOCKING,
        fields=["main_event.title", "main_event.event_start"],
        action="检查已有草案，避免重复创建。",
    )


ALL_RULES = (
    rule_field_001,
    rule_field_002,
    rule_time_001,
    rule_time_002,
    rule_time_003,
    rule_time_004,
    rule_time_005,
    rule_deadline_001,
    rule_deadline_002,
    rule_evidence_001,
    rule_evidence_002,
    rule_evidence_003,
    rule_confidence_001,
    rule_notice_001,
    rule_duplicate_001,
)

