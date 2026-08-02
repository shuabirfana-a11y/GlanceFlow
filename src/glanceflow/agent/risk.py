from __future__ import annotations

from glanceflow.agent.models import AgentObservation, RiskLevel


CRITICAL_RISKS = {
    "date_weekday_contradiction",
    "expired_notice",
    "deadline_role_contradiction",
    "duplicate_event",
    "transaction_id_mismatch",
    "readback_mismatch",
}
HIGH_RISKS = {
    "poor_image_quality",
    "low_ocr_confidence",
    "insufficient_evidence",
    "multiple_time_ambiguity",
    "calendar_conflict",
    "moving_user",
    "confirmation_expired",
    "draft_changed_after_confirmation",
    "partial_transaction",
    "unexpected_tool_output",
}


class RiskAssessment:
    def __init__(self, level: RiskLevel, factors: list[str], rules: list[str]) -> None:
        self.level = level
        self.factors = factors
        self.rules = rules


def assess_risk(observation: AgentObservation) -> RiskAssessment:
    factors = set(observation.detected_risks) - {"moving_user", "calendar_conflict", "duplicate_event"}
    if observation.motion_state in {"MOVING", "UNKNOWN"}:
        factors.add("moving_user")
    preflight = observation.preflight_result or {}
    if (preflight.get("duplicate_result") or {}).get("is_duplicate"):
        factors.add("duplicate_event")
    if (preflight.get("conflict_result") or {}).get("has_conflict"):
        factors.add("calendar_conflict")
    safety = observation.safety_decision or {}
    status = safety.get("status")
    if status == "CONTRADICTION_BLOCKED":
        factors.add("date_weekday_contradiction")
    elif status == "RECAPTURE_REQUIRED":
        factors.add("insufficient_evidence")

    critical = sorted(factors & CRITICAL_RISKS)
    high = sorted(factors & HIGH_RISKS)
    if critical:
        return RiskAssessment(RiskLevel.CRITICAL, sorted(factors), [f"risk.critical.{item}" for item in critical])
    if high:
        return RiskAssessment(RiskLevel.HIGH, sorted(factors), [f"risk.high.{item}" for item in high])
    if observation.unresolved_fields:
        return RiskAssessment(RiskLevel.MEDIUM, sorted(factors), ["risk.medium.unresolved_fields"])
    return RiskAssessment(RiskLevel.LOW, sorted(factors), ["risk.low.complete_and_consistent"])
