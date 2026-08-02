from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from glanceflow.agent.models import AgentSessionState, SideEffectLevel


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionInput(ToolModel):
    session_id: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class TransactionInput(SessionInput):
    transaction_id: str = Field(min_length=1)


class ToolOutput(ToolModel):
    data: dict[str, Any] = Field(default_factory=dict)
    verified: bool = False


ToolHandler = Callable[[BaseModel], BaseModel | dict[str, Any]]


@dataclass(frozen=True)
class ToolContract:
    tool_name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    required_session_states: frozenset[AgentSessionState]
    resulting_session_states: frozenset[AgentSessionState]
    side_effect_level: SideEffectLevel
    requires_user_confirmation: bool
    idempotent: bool
    timeout_seconds: float
    maximum_retries: int
    allowed_failure_recovery: tuple[str, ...]


def standard_contracts() -> tuple[ToolContract, ...]:
    state = AgentSessionState
    read = SideEffectLevel.READ_ONLY
    local = SideEffectLevel.LOCAL_STATE_CHANGE
    external = SideEffectLevel.EXTERNAL_REVERSIBLE_ACTION
    return (
        ToolContract("capture_frames", "短时采集并默认删除原视频。", SessionInput, ToolOutput, frozenset({state.IDLE, state.CAPTURING, state.RECAPTURE_REQUIRED}), frozenset({state.SELECTING_FRAME}), local, False, False, 8, 0, ("REQUEST_RECAPTURE", "FAIL")),
        ToolContract("select_best_frame", "从采样帧中自动选择证据帧。", SessionInput, ToolOutput, frozenset({state.SELECTING_FRAME}), frozenset({state.READING, state.RECAPTURE_REQUIRED}), read, False, True, 5, 1, ("RETRY", "REQUEST_RECAPTURE")),
        ToolContract("recognize_text", "调用现有本地 OCR 能力。", SessionInput, ToolOutput, frozenset({state.READING}), frozenset({state.EXTRACTING, state.RECAPTURE_REQUIRED}), read, False, True, 15, 2, ("RETRY", "REQUEST_RECAPTURE")),
        ToolContract("extract_notice_draft", "调用现有字段抽取器形成候选草稿。", SessionInput, ToolOutput, frozenset({state.EXTRACTING}), frozenset({state.VALIDATING, state.NEED_INPUT, state.BLOCKED}), read, False, True, 8, 1, ("RETRY", "ASK_USER", "BLOCK")),
        ToolContract("evaluate_safety", "调用现有 Safety Gate，不修改其规则。", SessionInput, ToolOutput, frozenset({state.VALIDATING}), frozenset({state.PREFLIGHTING, state.NEED_INPUT, state.RECAPTURE_REQUIRED, state.BLOCKED}), read, False, True, 5, 0, ("ASK_USER", "REQUEST_RECAPTURE", "BLOCK")),
        ToolContract("run_action_preflight", "调用现有 Action Preflight 检查重复与冲突。", SessionInput, ToolOutput, frozenset({state.PREFLIGHTING}), frozenset({state.WAIT_CONFIRM, state.BLOCKED}), read, False, True, 10, 1, ("RETRY", "BLOCK")),
        ToolContract("create_calendar_transaction", "通过 TrustedSchedulingService 执行已确认事务。", TransactionInput, ToolOutput, frozenset({state.EXECUTING}), frozenset({state.VERIFYING, state.RECOVERING}), external, True, True, 20, 0, ("CHECK_IDEMPOTENCY_KEY", "ROLLBACK")),
        ToolContract("verify_calendar_transaction", "回读并校验事务创建结果。", TransactionInput, ToolOutput, frozenset({state.VERIFYING, state.RECOVERING}), frozenset({state.SUCCESS, state.RECOVERING}), read, False, True, 10, 2, ("RETRY", "ROLLBACK")),
        ToolContract("rollback_calendar_transaction", "按事务事件标识补偿回滚并验证删除。", TransactionInput, ToolOutput, frozenset({state.RECOVERING}), frozenset({state.FAILED, state.BLOCKED}), external, False, True, 20, 1, ("RETRY", "BLOCK")),
        ToolContract("undo_last_transaction", "按已验证事务精确撤销。", TransactionInput, ToolOutput, frozenset({state.EXECUTING}), frozenset({state.UNDONE, state.RECOVERING}), external, True, True, 20, 0, ("CHECK_IDEMPOTENCY_KEY", "BLOCK")),
    )


class AgentRuntimePorts:
    """Explicit adapters around existing capabilities; this class owns no business logic."""

    def __init__(self, **handlers: ToolHandler) -> None:
        self.handlers = handlers

    def handler(self, name: str) -> ToolHandler:
        try:
            return self.handlers[name]
        except KeyError as exc:
            raise RuntimeError(f"runtime adapter is not configured for {name}") from exc
