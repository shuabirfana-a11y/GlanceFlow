from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from glanceflow.agent.models import (
    AgentActionType,
    AgentDecision,
    AgentGoal,
    AgentGoalType,
    AgentObservation,
    AgentSessionState,
    RiskLevel,
    ToolExecutionResult,
)
from glanceflow.agent.policy import AgentPolicy
from glanceflow.agent.recovery import RecoveryAction, RecoveryPolicy
from glanceflow.agent.registry import AgentToolRegistry
from glanceflow.agent.risk import assess_risk
from glanceflow.agent.state import AgentSession, AgentStateError, confirmation_digest
from glanceflow.agent.trace import DecisionTrace, DecisionTraceStep, result_for_trace


class AgentOrchestrationError(RuntimeError):
    pass


class GlanceFlowAgent:
    """Policy-driven coordinator. It has no direct OCR or CalendarPort dependency."""

    def __init__(
        self,
        registry: AgentToolRegistry,
        *,
        policy: AgentPolicy | None = None,
        recovery: RecoveryPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.policy = policy or AgentPolicy()
        self.recovery = recovery or RecoveryPolicy()
        self._sessions: dict[str, AgentSession] = {}
        self._traces: dict[str, DecisionTrace] = {}

    def start_goal(self, goal: AgentGoal) -> AgentSession:
        if goal.session_id in self._sessions:
            raise AgentOrchestrationError("session_id already exists")
        observation = AgentObservation(
            session_state=AgentSessionState.IDLE,
            motion_state="UNKNOWN",
            timestamp=datetime.now(timezone.utc),
        )
        session = AgentSession(session_id=goal.session_id, goal=goal, observation=observation)
        self._sessions[goal.session_id] = session
        self._traces[goal.session_id] = DecisionTrace(session_id=goal.session_id, goal_id=goal.goal_id)
        return session.model_copy(deep=True)

    def observe(self, session_id: str, observation: AgentObservation | dict[str, Any]) -> AgentSession:
        session = self._session(session_id)
        before = confirmation_digest(session.observation, session.risk_level) if session.confirmation_snapshot else None
        if isinstance(observation, AgentObservation):
            updated = observation
        else:
            payload = session.observation.model_dump(mode="python")
            payload.update(observation)
            payload["timestamp"] = payload.get("timestamp") or datetime.now(timezone.utc)
            updated = AgentObservation.model_validate(payload)
        session.observation = updated
        assessment = assess_risk(updated)
        severity = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}
        if severity[assessment.level] > severity[session.risk_level] and session.confirmation_snapshot:
            session.invalidate_confirmation()
        session.risk_level = assessment.level
        session.observation.detected_risks = assessment.factors
        if before and before != confirmation_digest(session.observation, session.risk_level):
            session.invalidate_confirmation()
            if "draft_changed_after_confirmation" not in session.observation.detected_risks:
                session.observation.detected_risks.append("draft_changed_after_confirmation")
                session.risk_level = assess_risk(session.observation).level
        return session.model_copy(deep=True)

    def decide_next_action(self, session_id: str) -> AgentDecision:
        session = self._session(session_id)
        assessment = assess_risk(session.observation)
        session.risk_level = assessment.level
        session.observation.detected_risks = assessment.factors
        return self.policy.select(session)

    def execute_next_action(self, session_id: str) -> ToolExecutionResult | None:
        session = self._session(session_id)
        decision = self.decide_next_action(session_id)
        current = session.observation.session_state
        available = self.policy.enumerate_allowed_actions(session)
        if decision.tool_name is None:
            self._apply_non_tool_action(session, decision)
            self._record(session, decision, current, available, None, verification_completed=False)
            return None

        if decision.selected_action is AgentActionType.UNDO_TRANSACTION and current is AgentSessionState.IDLE:
            session.transition(AgentSessionState.EXECUTING)
        if decision.selected_action is AgentActionType.START_CAPTURE and current is AgentSessionState.IDLE:
            session.transition(AgentSessionState.CAPTURING)
        if decision.selected_action is AgentActionType.EXECUTE_TRANSACTION and current is AgentSessionState.WAIT_CONFIRM:
            session.transition(AgentSessionState.EXECUTING)

        raw_input: dict[str, Any] = {
            "session_id": session.session_id,
            "payload": self._tool_payload(session, decision),
        }
        if decision.selected_action in {
            AgentActionType.EXECUTE_TRANSACTION,
            AgentActionType.VERIFY_TRANSACTION,
            AgentActionType.ROLLBACK_TRANSACTION,
            AgentActionType.UNDO_TRANSACTION,
        }:
            transaction_id = session.last_transaction_id or session.goal.target_transaction_id
            if not transaction_id:
                result = self._synthetic_failure(decision.tool_name, "VALIDATION_ERROR", "缺少事务标识。")
                self.handle_tool_result(session_id, decision, result, current, available)
                return result
            raw_input["transaction_id"] = transaction_id

        result = self.registry.execute(
            decision.tool_name,
            raw_input,
            session_state=session.observation.session_state,
            confirmation_valid=session.confirmation_valid(),
        )
        session.tool_call_count += 1
        if result.side_effect_occurred:
            session.side_effect_count += 1
        self.handle_tool_result(session_id, decision, result, current, available)
        return result

    def handle_tool_result(
        self,
        session_id: str,
        decision: AgentDecision,
        result: ToolExecutionResult,
        previous_state: AgentSessionState | None = None,
        available_actions: list[AgentActionType] | None = None,
    ) -> AgentSession:
        session = self._session(session_id)
        session.observation.last_tool_result = result.model_dump(mode="json")
        verified = False
        if result.success:
            verified = self._apply_success(session, decision.selected_action, result)
        else:
            contract = self.registry.contract(result.tool_name)
            retries = session.retry_counts.get(result.tool_name, 0)
            recovery = self.recovery.decide(
                result,
                side_effect_level=contract.side_effect_level,
                retry_count=retries,
                maximum_retries=contract.maximum_retries,
            )
            if recovery.action is RecoveryAction.RETRY:
                session.retry_counts[result.tool_name] = retries + 1
            elif recovery.action in {RecoveryAction.CHECK_IDEMPOTENCY_KEY, RecoveryAction.ROLLBACK}:
                session.invalidate_confirmation()
                if session.observation.session_state is not AgentSessionState.RECOVERING:
                    session.transition(AgentSessionState.RECOVERING)
                if result.error_type in {"PARTIAL_SUCCESS", "READBACK_MISMATCH"}:
                    session.observation.detected_risks.append("partial_transaction" if result.error_type == "PARTIAL_SUCCESS" else "readback_mismatch")
            elif recovery.action is RecoveryAction.BLOCK:
                session.transition(AgentSessionState.BLOCKED)
            else:
                session.transition(AgentSessionState.FAILED)
        session.observation.timestamp = datetime.now(timezone.utc)
        assessment = assess_risk(session.observation)
        session.risk_level = assessment.level
        session.observation.detected_risks = assessment.factors
        self._record(
            session,
            decision,
            previous_state or session.observation.session_state,
            available_actions or self.policy.enumerate_allowed_actions(session),
            result,
            verification_completed=verified,
        )
        return session.model_copy(deep=True)

    def handle_user_response(self, session_id: str, response: str | dict[str, Any]) -> AgentSession:
        session = self._session(session_id)
        state = session.observation.session_state
        if state is AgentSessionState.NEED_INPUT:
            if not isinstance(response, dict) or len(response) != 1:
                raise AgentOrchestrationError("澄清响应必须只包含一个结构化字段。")
            field, value = next(iter(response.items()))
            if field not in session.observation.unresolved_fields:
                raise AgentOrchestrationError("该字段不是当前必要澄清项。")
            session.clarification_counts[field] = session.clarification_counts.get(field, 0) + 1
            if value is None or (isinstance(value, str) and not value.strip()):
                session.observation.timestamp = datetime.now(timezone.utc)
                return session.model_copy(deep=True)
            draft = dict(session.observation.notice_draft or {})
            main = dict(draft.get("main_event") or {})
            main[field] = value
            draft["main_event"] = main
            session.observation.notice_draft = draft
            session.observation.unresolved_fields.remove(field)
            session.invalidate_confirmation()
            session.transition(AgentSessionState.VALIDATING)
        elif state is AgentSessionState.WAIT_CONFIRM:
            phrase = str(response).strip()
            conflict = "calendar_conflict" in session.observation.detected_risks
            changed = "draft_changed_after_confirmation" in session.observation.detected_risks
            required = "仍然创建" if conflict else ("重新确认" if changed else "确认")
            if phrase != required:
                raise AgentOrchestrationError(f"当前需要明确回复“{required}”。")
            session.issue_confirmation(phrase)
            session.observation.user_confirmation = {
                "phrase": phrase,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            raise AgentOrchestrationError("当前状态不接受用户响应。")
        session.observation.timestamp = datetime.now(timezone.utc)
        return session.model_copy(deep=True)

    def cancel(self, session_id: str) -> AgentSession:
        session = self._session(session_id)
        if session.observation.session_state in {AgentSessionState.SUCCESS, AgentSessionState.UNDONE}:
            raise AgentOrchestrationError("已完成事务不能用取消代替撤销。")
        if session.observation.session_state in {AgentSessionState.EXECUTING, AgentSessionState.VERIFYING, AgentSessionState.RECOVERING}:
            raise AgentOrchestrationError("事务执行、验证或恢复期间不能取消；必须先完成结果核验。")
        if session.observation.session_state in {AgentSessionState.CANCELLED, AgentSessionState.BLOCKED, AgentSessionState.FAILED}:
            return session.model_copy(deep=True)
        session.invalidate_confirmation()
        session.transition(AgentSessionState.CANCELLED)
        return session.model_copy(deep=True)

    def undo_last(self, session_id: str, transaction_id: str) -> AgentSession:
        session = self._session(session_id)
        if session.observation.session_state is not AgentSessionState.SUCCESS:
            raise AgentOrchestrationError("只有已验证成功的事务可以精确撤销。")
        session.goal = session.goal.model_copy(update={"goal_type": AgentGoalType.UNDO_LAST_TRANSACTION, "target_transaction_id": transaction_id})
        session.last_transaction_id = transaction_id
        session.issue_confirmation("确认")
        session.transition(AgentSessionState.EXECUTING)
        return session.model_copy(deep=True)

    def get_state(self, session_id: str) -> AgentSession:
        return self._session(session_id).model_copy(deep=True)

    def get_trace(self, session_id: str) -> DecisionTrace:
        self._session(session_id)
        return self._traces[session_id].model_copy(deep=True)

    def snapshot_session(self, session_id: str) -> dict[str, Any]:
        session = self._session(session_id)
        return {
            "schema_version": "agent-session-v1",
            "session": session.model_dump(mode="json"),
            "trace": self._traces[session_id].model_dump(mode="json"),
        }

    def restore_session(self, snapshot: dict[str, Any]) -> AgentSession:
        if snapshot.get("schema_version") != "agent-session-v1":
            raise AgentOrchestrationError("unsupported agent snapshot schema")
        session = AgentSession.model_validate(snapshot.get("session"))
        trace = DecisionTrace.model_validate(snapshot.get("trace"))
        if session.session_id in self._sessions or trace.session_id != session.session_id:
            raise AgentOrchestrationError("snapshot session identity is invalid or already active")
        session.invalidate_confirmation()
        if session.observation.session_state in {AgentSessionState.EXECUTING, AgentSessionState.VERIFYING}:
            session.transition(AgentSessionState.RECOVERING)
        self._sessions[session.session_id] = session
        self._traces[session.session_id] = trace
        return session.model_copy(deep=True)

    def _apply_success(self, session: AgentSession, action: AgentActionType, result: ToolExecutionResult) -> bool:
        data = result.output.get("data", {})
        verified = bool(result.output.get("verified"))
        observation = session.observation
        if action is AgentActionType.START_CAPTURE:
            observation.capture_result = data
            session.transition(AgentSessionState.SELECTING_FRAME)
        elif action is AgentActionType.SELECT_FRAME:
            if data.get("requires_recapture") or not data.get("frame_id"):
                observation.detected_risks.append("poor_image_quality")
                session.transition(AgentSessionState.RECAPTURE_REQUIRED)
            else:
                observation.selected_frame = data
                session.transition(AgentSessionState.READING)
        elif action is AgentActionType.RUN_OCR:
            observation.ocr_result = data
            session.transition(AgentSessionState.EXTRACTING)
        elif action is AgentActionType.EXTRACT_DRAFT:
            observation.notice_draft = data.get("notice_draft") or data
            observation.unresolved_fields = list(data.get("unresolved_fields", []))
            session.transition(AgentSessionState.VALIDATING if not observation.unresolved_fields else AgentSessionState.NEED_INPUT)
        elif action is AgentActionType.RUN_SAFETY_GATE:
            observation.safety_decision = data
            status = data.get("status")
            if status == "READY_TO_CONFIRM":
                session.transition(AgentSessionState.PREFLIGHTING)
            elif status == "NEED_USER_INPUT":
                observation.unresolved_fields = list(data.get("required_user_inputs", observation.unresolved_fields))
                session.transition(AgentSessionState.NEED_INPUT)
            elif status == "RECAPTURE_REQUIRED":
                session.transition(AgentSessionState.RECAPTURE_REQUIRED)
            else:
                session.transition(AgentSessionState.BLOCKED)
        elif action is AgentActionType.RUN_PREFLIGHT:
            observation.preflight_result = data
            session.last_transaction_id = data.get("transaction_id")
            if (data.get("duplicate_result") or {}).get("is_duplicate") or not data.get("passed", False):
                observation.detected_risks.append("duplicate_event")
                session.transition(AgentSessionState.BLOCKED)
            else:
                if (data.get("conflict_result") or {}).get("has_conflict"):
                    observation.detected_risks.append("calendar_conflict")
                session.transition(AgentSessionState.WAIT_CONFIRM)
        elif action is AgentActionType.EXECUTE_TRANSACTION:
            observation.calendar_transaction = data
            session.invalidate_confirmation()
            if data.get("status") in {"PARTIAL", "ROLLED_BACK", "FAILED"}:
                observation.detected_risks.append("partial_transaction")
                session.transition(AgentSessionState.RECOVERING)
            else:
                session.transition(AgentSessionState.VERIFYING)
        elif action is AgentActionType.VERIFY_TRANSACTION:
            observation.calendar_transaction = data
            if verified and data.get("status") in {"VERIFIED", "UNDONE"}:
                session.transition(AgentSessionState.SUCCESS if data.get("status") == "VERIFIED" else AgentSessionState.UNDONE)
            else:
                observation.detected_risks.append("readback_mismatch")
                session.transition(AgentSessionState.RECOVERING)
        elif action is AgentActionType.ROLLBACK_TRANSACTION:
            observation.calendar_transaction = data
            session.transition(AgentSessionState.FAILED if verified else AgentSessionState.BLOCKED)
        elif action is AgentActionType.UNDO_TRANSACTION:
            observation.calendar_transaction = data
            session.invalidate_confirmation()
            session.transition(AgentSessionState.UNDONE if verified else AgentSessionState.RECOVERING)
        return verified

    def _apply_non_tool_action(self, session: AgentSession, decision: AgentDecision) -> None:
        if decision.selected_action is AgentActionType.BLOCK and session.observation.session_state is not AgentSessionState.BLOCKED:
            session.transition(AgentSessionState.BLOCKED)
        elif decision.selected_action is AgentActionType.FAIL and session.observation.session_state is not AgentSessionState.FAILED:
            session.transition(AgentSessionState.FAILED)

    def _tool_payload(self, session: AgentSession, decision: AgentDecision) -> dict[str, Any]:
        return {
            "goal": session.goal.model_dump(mode="json"),
            "observation": session.observation.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
        }

    def _record(
        self,
        session: AgentSession,
        decision: AgentDecision,
        previous_state: AgentSessionState,
        available: list[AgentActionType],
        result: ToolExecutionResult | None,
        *,
        verification_completed: bool,
    ) -> None:
        evidence = [line.get("line_id") for line in (session.observation.notice_draft or {}).get("evidence_lines", []) if line.get("line_id")]
        self._traces[session.session_id].append(DecisionTraceStep(
            occurred_at=datetime.now(timezone.utc),
            current_state=previous_state,
            current_goal=session.goal.goal_type,
            available_actions=available,
            selected_action=decision.selected_action,
            policy_rules_triggered=decision.policy_rules_triggered,
            risk_level=session.risk_level,
            evidence_line_ids=evidence,
            tool_call=decision.tool_name,
            tool_result=result_for_trace(result),
            next_state=session.observation.session_state,
            side_effect_occurred=bool(result and result.side_effect_occurred),
            verification_completed=verification_completed,
            public_rationale=decision.public_rationale,
        ))

    def _session(self, session_id: str) -> AgentSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise AgentOrchestrationError("unknown agent session") from exc

    @staticmethod
    def _synthetic_failure(tool_name: str, error_type: str, message: str) -> ToolExecutionResult:
        now = datetime.now(timezone.utc)
        return ToolExecutionResult(
            tool_name=tool_name,
            success=False,
            error_type=error_type,
            error_message=message,
            started_at=now,
            completed_at=now,
            duration_ms=0,
        )
