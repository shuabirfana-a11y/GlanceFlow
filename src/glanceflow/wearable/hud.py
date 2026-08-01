from __future__ import annotations

from glanceflow.wearable.models import GlanceFlowSession, HudState, MotionState, SessionStatus


def build_hud(session: GlanceFlowSession) -> HudState:
    status = session.status
    common = {"session_id": session.session_id, "status": status}
    if status is SessionStatus.IDLE:
        return HudState(**common, headline="见程就绪", primary_text="说“帮我安排”后开始短时采集。", prompt="等待明确语音触发", severity="info")
    if status is SessionStatus.CAPTURING:
        return HudState(**common, headline="正在看通知", primary_text="仅采集触发后的短视频。", prompt="保持画面稳定", severity="info", can_cancel=True)
    if status in {SessionStatus.SELECTING_FRAME, SessionStatus.PROCESSING}:
        return HudState(**common, headline="正在识别", primary_text="自动选帧并核对通知内容。", severity="info", can_cancel=True)
    if status is SessionStatus.RECAPTURE:
        reason = _first_reason(session, "画面不够清楚。")
        return HudState(**common, headline="请重新拍摄", primary_text=reason[:96], prompt="正对通知并保持稳定", severity="warning", can_cancel=True)
    if status is SessionStatus.NEED_INPUT:
        reason = _first_reason(session, "还缺少必要信息。")
        return HudState(**common, headline="需要补充", primary_text=reason[:96], prompt="请补充后重新采集", severity="warning", can_cancel=True)
    if status is SessionStatus.BLOCKED:
        reason = _first_reason(session, "通知内容存在矛盾。")
        return HudState(**common, headline="已阻止创建", primary_text=reason[:96], severity="danger", can_cancel=True)
    if status is SessionStatus.WAIT_CONFIRM:
        draft = session.pipeline_result.extraction_result.draft if session.pipeline_result and session.pipeline_result.extraction_result else None
        title = draft.main_event.title if draft else "待确认日程"
        when = draft.main_event.event_start.strftime("%m月%d日 %H:%M") if draft else ""
        if session.motion_state is not MotionState.STATIONARY:
            return HudState(**common, headline="请先停稳", primary_text=f"{title} · {when}"[:96], secondary_text="移动中不会写入日历。", prompt="停稳后说“确认”", severity="warning", can_cancel=True)
        conflict = bool(session.preflight_result and session.preflight_result.requires_conflict_confirmation)
        return HudState(
            **common,
            headline="日程冲突" if conflict else "确认日程",
            primary_text=f"{title} · {when}"[:96],
            secondary_text="与已有日程重叠，确认仍创建。" if conflict else "核对无误后再创建。",
            prompt="说“确认”或“取消”",
            severity="warning" if conflict else "info",
            can_confirm=True,
            can_cancel=True,
        )
    if status is SessionStatus.EXECUTING:
        return HudState(**common, headline="正在创建", primary_text="写入后将立即回读核验。", severity="info")
    if status is SessionStatus.SUCCESS:
        undone = bool(session.transaction and session.transaction.status.value == "UNDONE")
        return HudState(**common, headline="已撤销" if undone else "创建成功", primary_text="刚才的日程已删除。" if undone else "日程已创建并通过回读核验。", severity="success", can_undo=not undone)
    if status is SessionStatus.CANCELLED:
        return HudState(**common, headline="已取消", primary_text="没有创建新的日历事件。", severity="info")
    return HudState(**common, headline="处理失败", primary_text=_first_reason(session, "未创建日历事件。")[:96], prompt="可重新开始", severity="danger")


def _first_reason(session: GlanceFlowSession, fallback: str) -> str:
    if session.pipeline_result and session.pipeline_result.reasons:
        return session.pipeline_result.reasons[0]
    if session.preflight_result and session.preflight_result.messages:
        return session.preflight_result.messages[0]
    if session.selection_result:
        return session.selection_result.reason
    return fallback
