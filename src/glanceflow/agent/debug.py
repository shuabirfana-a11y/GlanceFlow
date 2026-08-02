from __future__ import annotations

from typing import Any

from glanceflow.agent.models import AgentActionType, AgentObservation, AgentSessionState
from glanceflow.agent.risk import assess_risk
from glanceflow.wearable.models import GlanceFlowSession, SessionStatus


STATE_MAP = {
    SessionStatus.IDLE: AgentSessionState.IDLE,
    SessionStatus.CAPTURING: AgentSessionState.CAPTURING,
    SessionStatus.SELECTING_FRAME: AgentSessionState.SELECTING_FRAME,
    SessionStatus.PROCESSING: AgentSessionState.VALIDATING,
    SessionStatus.WAIT_CONFIRM: AgentSessionState.WAIT_CONFIRM,
    SessionStatus.EXECUTING: AgentSessionState.EXECUTING,
    SessionStatus.SUCCESS: AgentSessionState.SUCCESS,
    SessionStatus.RECAPTURE: AgentSessionState.RECAPTURE_REQUIRED,
    SessionStatus.NEED_INPUT: AgentSessionState.NEED_INPUT,
    SessionStatus.BLOCKED: AgentSessionState.BLOCKED,
    SessionStatus.FAILED: AgentSessionState.FAILED,
    SessionStatus.CANCELLED: AgentSessionState.CANCELLED,
}

NEXT_ACTION = {
    AgentSessionState.IDLE: AgentActionType.START_CAPTURE,
    AgentSessionState.CAPTURING: AgentActionType.SELECT_FRAME,
    AgentSessionState.SELECTING_FRAME: AgentActionType.SELECT_FRAME,
    AgentSessionState.VALIDATING: AgentActionType.RUN_SAFETY_GATE,
    AgentSessionState.NEED_INPUT: AgentActionType.ASK_USER,
    AgentSessionState.RECAPTURE_REQUIRED: AgentActionType.REQUEST_RECAPTURE,
    AgentSessionState.WAIT_CONFIRM: AgentActionType.WAIT_FOR_CONFIRMATION,
    AgentSessionState.EXECUTING: AgentActionType.VERIFY_TRANSACTION,
    AgentSessionState.SUCCESS: AgentActionType.COMPLETE,
    AgentSessionState.BLOCKED: AgentActionType.BLOCK,
    AgentSessionState.FAILED: AgentActionType.FAIL,
    AgentSessionState.CANCELLED: AgentActionType.COMPLETE,
}


def build_agent_debug_summary(session: GlanceFlowSession) -> dict[str, Any]:
    state = STATE_MAP[session.status]
    pipeline = session.pipeline_result
    safety = pipeline.safety_decision.model_dump(mode="json") if pipeline and pipeline.safety_decision else None
    draft = pipeline.extraction_result.draft.model_dump(mode="json") if pipeline and pipeline.extraction_result and pipeline.extraction_result.draft else None
    preflight = session.preflight_result.model_dump(mode="json") if session.preflight_result else None
    unresolved = list(safety.get("required_user_inputs", [])) if safety else []
    observation = AgentObservation(
        session_state=state,
        notice_draft=draft,
        safety_decision=safety,
        preflight_result=preflight,
        motion_state=session.motion_state.value,
        unresolved_fields=unresolved,
        timestamp=session.updated_at,
    )
    risk = assess_risk(observation)
    action = NEXT_ACTION.get(state, AgentActionType.FAIL)
    waiting_for = unresolved[:1]
    if state is AgentSessionState.WAIT_CONFIRM:
        waiting_for = ["仍然创建" if "calendar_conflict" in risk.factors else "确认"]
    recent = session.audit_events[-1] if session.audit_events else None
    rationale = {
        AgentSessionState.WAIT_CONFIRM: "安全门与行动预检已完成，外部写入仍需结构化确认。",
        AgentSessionState.RECAPTURE_REQUIRED: "当前证据质量不足，禁止进入确认与日历写入。",
        AgentSessionState.BLOCKED: "确定性安全规则或重复检查阻止了当前动作。",
        AgentSessionState.SUCCESS: "事务已创建并通过回读验证。",
    }.get(state, "根据当前会话状态显示下一项受控动作。")
    return {
        "goal": "SCHEDULE_CURRENT_NOTICE",
        "state": state.value,
        "risk_level": risk.level.value,
        "next_action": action.value,
        "public_rationale": rationale,
        "waiting_for": waiting_for,
        "recent_tool_result": {"action": recent.action, "message": recent.message} if recent else None,
    }
