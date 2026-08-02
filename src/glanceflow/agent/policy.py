from __future__ import annotations

from datetime import datetime, timezone

from glanceflow.agent.clarification import ClarificationPolicy
from glanceflow.agent.models import AgentActionType, AgentDecision, AgentGoalType, AgentSessionState, RiskLevel
from glanceflow.agent.state import AgentSession


ACTION_TO_TOOL = {
    AgentActionType.START_CAPTURE: "capture_frames",
    AgentActionType.SELECT_FRAME: "select_best_frame",
    AgentActionType.RUN_OCR: "recognize_text",
    AgentActionType.EXTRACT_DRAFT: "extract_notice_draft",
    AgentActionType.RUN_SAFETY_GATE: "evaluate_safety",
    AgentActionType.RUN_PREFLIGHT: "run_action_preflight",
    AgentActionType.EXECUTE_TRANSACTION: "create_calendar_transaction",
    AgentActionType.VERIFY_TRANSACTION: "verify_calendar_transaction",
    AgentActionType.ROLLBACK_TRANSACTION: "rollback_calendar_transaction",
    AgentActionType.UNDO_TRANSACTION: "undo_last_transaction",
}


class AgentPolicy:
    version = "agent-policy-v1"

    def __init__(self, clarification: ClarificationPolicy | None = None) -> None:
        self.clarification = clarification or ClarificationPolicy()

    def enumerate_allowed_actions(self, session: AgentSession) -> list[AgentActionType]:
        state = session.observation.session_state
        if session.goal.goal_type is AgentGoalType.CANCEL_CURRENT_ACTION:
            return [AgentActionType.COMPLETE] if state is AgentSessionState.CANCELLED else [AgentActionType.BLOCK]
        if session.goal.goal_type is AgentGoalType.UNDO_LAST_TRANSACTION:
            return [AgentActionType.UNDO_TRANSACTION] if state in {AgentSessionState.IDLE, AgentSessionState.SUCCESS, AgentSessionState.EXECUTING} else [AgentActionType.BLOCK]
        mapping = {
            AgentSessionState.IDLE: [AgentActionType.START_CAPTURE],
            AgentSessionState.CAPTURING: [AgentActionType.SELECT_FRAME],
            AgentSessionState.SELECTING_FRAME: [AgentActionType.SELECT_FRAME],
            AgentSessionState.READING: [AgentActionType.RUN_OCR],
            AgentSessionState.EXTRACTING: [AgentActionType.EXTRACT_DRAFT],
            AgentSessionState.VALIDATING: [AgentActionType.RUN_SAFETY_GATE],
            AgentSessionState.PREFLIGHTING: [AgentActionType.RUN_PREFLIGHT],
            AgentSessionState.NEED_INPUT: [AgentActionType.ASK_USER, AgentActionType.BLOCK],
            AgentSessionState.RECAPTURE_REQUIRED: [AgentActionType.REQUEST_RECAPTURE],
            AgentSessionState.WAIT_CONFIRM: [AgentActionType.WAIT_FOR_CONFIRMATION, AgentActionType.EXECUTE_TRANSACTION],
            AgentSessionState.EXECUTING: [AgentActionType.EXECUTE_TRANSACTION],
            AgentSessionState.VERIFYING: [AgentActionType.VERIFY_TRANSACTION],
            AgentSessionState.RECOVERING: [AgentActionType.ROLLBACK_TRANSACTION, AgentActionType.VERIFY_TRANSACTION, AgentActionType.FAIL],
            AgentSessionState.SUCCESS: [AgentActionType.COMPLETE],
            AgentSessionState.UNDONE: [AgentActionType.COMPLETE],
            AgentSessionState.CANCELLED: [AgentActionType.COMPLETE],
            AgentSessionState.BLOCKED: [AgentActionType.BLOCK],
            AgentSessionState.FAILED: [AgentActionType.FAIL],
        }
        return mapping.get(state, [AgentActionType.FAIL])

    def select(self, session: AgentSession) -> AgentDecision:
        available = self.enumerate_allowed_actions(session)
        risk = session.risk_level
        rules: list[str] = [f"state.{session.observation.session_state.value.lower()}"]
        required: list[str] = []
        rationale = "根据当前状态选择下一项白名单能力。"
        selected = available[0]

        if risk is RiskLevel.CRITICAL and session.observation.session_state not in {AgentSessionState.RECOVERING, AgentSessionState.VERIFYING}:
            selected = AgentActionType.BLOCK
            rules.append("critical_risk_blocks_action")
            rationale = "检测到确定性高危矛盾或重复，阻止外部操作。"
        elif session.observation.session_state is AgentSessionState.RECOVERING:
            last = session.observation.last_tool_result or {}
            if last.get("error_type") == "TIMEOUT":
                selected = AgentActionType.VERIFY_TRANSACTION
                rules.append("timeout_requires_idempotency_check")
                rationale = "写入超时后先按事务标识回读，禁止重复创建。"
            else:
                selected = AgentActionType.ROLLBACK_TRANSACTION
                rules.append("recovery_requires_rollback")
                rationale = "事务部分成功或回读不一致，执行补偿回滚并验证删除。"
        elif session.observation.session_state is AgentSessionState.NEED_INPUT:
            request = self.clarification.choose(session.observation.unresolved_fields, session.clarification_counts, session.observation.detected_risks)
            if request.exhausted:
                selected = AgentActionType.BLOCK
                rules.append("clarification_limit_reached")
                rationale = "必要字段两次澄清后仍未解决，保留草稿并阻止执行。"
            else:
                selected = AgentActionType.REQUEST_RECAPTURE if request.request_recapture else AgentActionType.ASK_USER
                required = [request.question] if request.question else []
                rules.append("minimal_clarification")
                rationale = request.question or "需要最小澄清。"
        elif session.observation.session_state is AgentSessionState.WAIT_CONFIRM:
            if "moving_user" in session.observation.detected_risks:
                selected = AgentActionType.WAIT_FOR_CONFIRMATION
                rules.append("motion_blocks_side_effect")
                required = ["等待静止"]
                rationale = "移动或姿态未知时禁止执行日历写入。"
            elif session.confirmation_valid():
                selected = AgentActionType.EXECUTE_TRANSACTION
                rules.append("confirmation_snapshot_valid")
                rationale = "确认快照与当前草稿、风险和冲突状态一致，可以执行事务。"
            else:
                selected = AgentActionType.WAIT_FOR_CONFIRMATION
                rules.append("confirmation_required")
                conflict = "calendar_conflict" in session.observation.detected_risks
                changed = "draft_changed_after_confirmation" in session.observation.detected_risks
                required = ["仍然创建" if conflict else ("重新确认" if changed else "确认")]
                rationale = "存在冲突，等待明确的“仍然创建”。" if conflict else ("草稿在确认后变化，旧确认已失效。" if changed else "草稿通过安全门和行动预检，等待用户确认。")
        rejected = [action for action in AgentActionType if action not in available and action is not selected]
        return AgentDecision(
            session_id=session.session_id,
            selected_action=selected,
            tool_name=ACTION_TO_TOOL.get(selected),
            risk_level=risk,
            preconditions_met=selected not in {AgentActionType.BLOCK, AgentActionType.FAIL},
            required_inputs=required,
            policy_rules_triggered=rules,
            rejected_actions=rejected,
            public_rationale=rationale,
            created_at=datetime.now(timezone.utc),
            policy_version=self.version,
        )
