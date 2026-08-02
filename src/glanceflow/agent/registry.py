from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from pydantic import BaseModel, ValidationError

from glanceflow.agent.models import AgentSessionState, SideEffectLevel, ToolExecutionResult
from glanceflow.agent.tools import AgentRuntimePorts, ToolContract, ToolHandler, standard_contracts


class ToolRegistryError(RuntimeError):
    pass


class AgentToolFailure(RuntimeError):
    def __init__(self, error_type: str, public_message: str, *, retryable: bool = False, side_effect_occurred: bool = False) -> None:
        super().__init__(public_message)
        self.error_type = error_type
        self.public_message = public_message
        self.retryable = retryable
        self.side_effect_occurred = side_effect_occurred


class AgentToolRegistry:
    def __init__(self) -> None:
        self._contracts: dict[str, ToolContract] = {}
        self._handlers: dict[str, ToolHandler] = {}

    @classmethod
    def from_ports(cls, ports: AgentRuntimePorts) -> "AgentToolRegistry":
        registry = cls()
        for contract in standard_contracts():
            registry.register(contract, ports.handler(contract.tool_name))
        return registry

    def register(self, contract: ToolContract, handler: ToolHandler) -> None:
        if contract.tool_name in self._contracts:
            raise ToolRegistryError(f"tool already registered: {contract.tool_name}")
        self._contracts[contract.tool_name] = contract
        self._handlers[contract.tool_name] = handler

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._contracts))

    def contract(self, name: str) -> ToolContract:
        try:
            return self._contracts[name]
        except KeyError as exc:
            raise ToolRegistryError(f"tool is not on the whitelist: {name}") from exc

    def execute(
        self,
        name: str,
        raw_input: dict[str, Any],
        *,
        session_state: AgentSessionState,
        confirmation_valid: bool,
    ) -> ToolExecutionResult:
        contract = self.contract(name)
        started_at = datetime.now(timezone.utc)
        clock = perf_counter()
        if session_state not in contract.required_session_states:
            return self._failure(name, started_at, clock, "POLICY_BLOCK", "当前状态不允许调用该工具。")
        if contract.requires_user_confirmation and not confirmation_valid:
            return self._failure(name, started_at, clock, "POLICY_BLOCK", "用户确认缺失、过期或与当前草稿不一致。")
        try:
            validated_input = contract.input_model.model_validate(raw_input)
        except ValidationError:
            return self._failure(name, started_at, clock, "VALIDATION_ERROR", "工具输入未通过结构化校验。")
        try:
            raw_output = self._handlers[name](validated_input)
            if isinstance(raw_output, BaseModel):
                raw_output = raw_output.model_dump(mode="python")
            output = contract.output_model.model_validate(raw_output)
        except ValidationError:
            return self._failure(name, started_at, clock, "OUTPUT_VALIDATION_ERROR", "工具输出未通过结构化校验。")
        except AgentToolFailure as exc:
            result = self._failure(name, started_at, clock, exc.error_type, exc.public_message, retryable=exc.retryable)
            return result.model_copy(update={"side_effect_occurred": exc.side_effect_occurred})
        except TimeoutError:
            return self._failure(name, started_at, clock, "TIMEOUT", "工具调用超时，结果状态未知。", retryable=contract.side_effect_level is SideEffectLevel.READ_ONLY)
        except Exception:
            return self._failure(name, started_at, clock, "TOOL_EXECUTION_ERROR", "工具执行失败；内部提供方信息已隐藏。", retryable=contract.side_effect_level is SideEffectLevel.READ_ONLY)
        completed = datetime.now(timezone.utc)
        return ToolExecutionResult(
            tool_name=name,
            success=True,
            output=output.model_dump(mode="json"),
            side_effect_occurred=contract.side_effect_level is SideEffectLevel.EXTERNAL_REVERSIBLE_ACTION,
            started_at=started_at,
            completed_at=completed,
            duration_ms=(perf_counter() - clock) * 1000,
        )

    @staticmethod
    def _failure(name: str, started_at: datetime, clock: float, error_type: str, message: str, retryable: bool = False) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=name,
            success=False,
            error_type=error_type,
            error_message=message,
            retryable=retryable,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            duration_ms=(perf_counter() - clock) * 1000,
        )
