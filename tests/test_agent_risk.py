from datetime import datetime, timezone

from glanceflow.agent.models import AgentObservation, AgentSessionState, RiskLevel
from glanceflow.agent.risk import assess_risk


def observation(**changes):
    base = {"session_state": AgentSessionState.VALIDATING, "timestamp": datetime.now(timezone.utc), "motion_state": "STATIONARY"}
    base.update(changes)
    return AgentObservation(**base)


def test_risk_levels_use_deterministic_overrides():
    assert assess_risk(observation()).level is RiskLevel.LOW
    assert assess_risk(observation(unresolved_fields=["location"])).level is RiskLevel.MEDIUM
    assert assess_risk(observation(detected_risks=["poor_image_quality"])).level is RiskLevel.HIGH
    result = assess_risk(observation(detected_risks=["poor_image_quality", "expired_notice"]))
    assert result.level is RiskLevel.CRITICAL
    assert "risk.critical.expired_notice" in result.rules


def test_motion_and_preflight_are_inferred_not_scored():
    assert assess_risk(observation(motion_state="MOVING")).level is RiskLevel.HIGH
    duplicate = observation(preflight_result={"duplicate_result": {"is_duplicate": True}})
    assert assess_risk(duplicate).level is RiskLevel.CRITICAL
