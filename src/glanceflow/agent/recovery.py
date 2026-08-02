from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from glanceflow.agent.models import SideEffectLevel, ToolExecutionResult


class RecoveryAction(StrEnum):
    RETRY = "RETRY"
    CHECK_IDEMPOTENCY_KEY = "CHECK_IDEMPOTENCY_KEY"
    VERIFY = "VERIFY"
    ROLLBACK = "ROLLBACK"
    BLOCK = "BLOCK"
    FAIL = "FAIL"


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    rationale: str


class RecoveryPolicy:
    def decide(
        self,
        result: ToolExecutionResult,
        *,
        side_effect_level: SideEffectLevel,
        retry_count: int,
        maximum_retries: int,
    ) -> RecoveryDecision:
        if result.success:
            return RecoveryDecision(RecoveryAction.VERIFY, "工具返回成功，继续验证结构化结果。")
        if side_effect_level is SideEffectLevel.READ_ONLY and result.retryable and retry_count < maximum_retries:
            return RecoveryDecision(RecoveryAction.RETRY, "只读工具暂时失败，在集中限制内重试。")
        if side_effect_level is SideEffectLevel.EXTERNAL_REVERSIBLE_ACTION:
            if result.error_type == "TIMEOUT":
                return RecoveryDecision(RecoveryAction.CHECK_IDEMPOTENCY_KEY, "外部写入超时，先按事务标识查询，禁止盲目重建。")
            if result.side_effect_occurred:
                return RecoveryDecision(RecoveryAction.ROLLBACK, "外部事务部分成功，回滚并验证删除。")
        if result.error_type in {"READBACK_MISMATCH", "PARTIAL_SUCCESS"}:
            return RecoveryDecision(RecoveryAction.ROLLBACK, "事务结果不一致，进入补偿回滚。")
        if result.error_type in {"POLICY_BLOCK", "VALIDATION_ERROR"}:
            return RecoveryDecision(RecoveryAction.BLOCK, "安全或结构化校验未通过。")
        return RecoveryDecision(RecoveryAction.FAIL, "故障无法在安全边界内自动恢复。")
