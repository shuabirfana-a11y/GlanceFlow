from __future__ import annotations

from glanceflow.config import MAX_USER_PROMPT_LENGTH
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.domain.models import NoticePackageDraft
from glanceflow.safety.results import SafetyGateDecision, ValidationResult
from glanceflow.safety.rules import ALL_RULES


_BLOCKING_RULES = {
    "GF-TIME-001",
    "GF-TIME-002",
    "GF-TIME-003",
    "GF-TIME-004",
    "GF-DEADLINE-002",
    "GF-NOTICE-001",
    "GF-DUPLICATE-001",
    "GF-TEMPORAL-001",
}
_RECAPTURE_RULES = {"GF-EVIDENCE-002", "GF-EVIDENCE-003", "GF-CONFIDENCE-001"}
_INPUT_RULES = {"GF-FIELD-001", "GF-FIELD-002", "GF-TIME-005", "GF-DEADLINE-001", "GF-EVIDENCE-001"}


def _prompt(result: ValidationResult) -> str:
    value = result.suggested_action or result.message
    return value[:MAX_USER_PROMPT_LENGTH]


def evaluate_notice(
    draft: NoticePackageDraft,
    existing_drafts: list[NoticePackageDraft] | None = None,
) -> SafetyGateDecision:
    """Evaluate all deterministic rules without modifying the input draft."""
    existing = list(existing_drafts or [])
    results = [rule(draft, existing) for rule in ALL_RULES]
    failures = [result for result in results if not result.passed]

    blocking = [_prompt(result) for result in failures if result.rule_id in _BLOCKING_RULES]
    recapture = [_prompt(result) for result in failures if result.rule_id in _RECAPTURE_RULES]
    required = [_prompt(result) for result in failures if result.rule_id in _INPUT_RULES]

    if blocking:
        status = SafetyGateStatus.CONTRADICTION_BLOCKED
    elif recapture:
        status = SafetyGateStatus.RECAPTURE_REQUIRED
    elif required:
        status = SafetyGateStatus.NEED_USER_INPUT
    else:
        status = SafetyGateStatus.READY_TO_CONFIRM

    passed_count = sum(result.passed for result in results)
    summary = f"安全门完成 {len(results)} 条规则：{passed_count} 条通过，{len(failures)} 条未通过；状态 {status.value}。"
    return SafetyGateDecision(
        status=status,
        can_proceed_to_confirmation=status is SafetyGateStatus.READY_TO_CONFIRM,
        rule_results=results,
        blocking_reasons=blocking,
        required_user_inputs=required,
        recapture_reasons=recapture,
        summary=summary,
        draft_snapshot=draft.model_dump(mode="json"),
    )
