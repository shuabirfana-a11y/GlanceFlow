from datetime import datetime, timezone

from glanceflow.agent.models import SideEffectLevel, ToolExecutionResult
from glanceflow.agent.recovery import RecoveryAction, RecoveryPolicy


def failure(error_type, *, retryable=False, side_effect=False):
    now = datetime.now(timezone.utc)
    return ToolExecutionResult(tool_name="x", success=False, error_type=error_type, error_message="public", retryable=retryable, side_effect_occurred=side_effect, started_at=now, completed_at=now, duration_ms=0)


def test_read_only_retry_is_limited():
    policy = RecoveryPolicy()
    assert policy.decide(failure("TEMP", retryable=True), side_effect_level=SideEffectLevel.READ_ONLY, retry_count=0, maximum_retries=1).action is RecoveryAction.RETRY
    assert policy.decide(failure("TEMP", retryable=True), side_effect_level=SideEffectLevel.READ_ONLY, retry_count=1, maximum_retries=1).action is RecoveryAction.FAIL


def test_side_effect_timeout_and_partial_success_do_not_blind_retry():
    policy = RecoveryPolicy()
    assert policy.decide(failure("TIMEOUT", side_effect=True), side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE_ACTION, retry_count=0, maximum_retries=0).action is RecoveryAction.CHECK_IDEMPOTENCY_KEY
    assert policy.decide(failure("PARTIAL_SUCCESS", side_effect=True), side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE_ACTION, retry_count=0, maximum_retries=0).action is RecoveryAction.ROLLBACK
