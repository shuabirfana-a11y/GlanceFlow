from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from glanceflow.application.scheduling_service import SchedulingValidationError, TrustedSchedulingService
from glanceflow.calendar.models import EventRole, TransactionStatus, UserConfirmation, calendar_request_digest
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.pipeline import process_image
from glanceflow.wearable.capture import CaptureError
from glanceflow.wearable.frame_selection import DeterministicFrameSelector
from glanceflow.wearable.hud import build_hud
from glanceflow.wearable.models import (
    CaptureRequest,
    GlanceFlowSession,
    HudState,
    MotionState,
    SessionAuditEvent,
    SessionStatus,
    StructuredConfirmationEvent,
    VoiceIntent,
)
from glanceflow.wearable.ports import FrameCapturePort, MotionProvider
from glanceflow.wearable.voice import interpret_voice


class SessionValidationError(RuntimeError):
    pass


_ALLOWED: dict[SessionStatus, set[SessionStatus]] = {
    SessionStatus.IDLE: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.CAPTURING: {SessionStatus.SELECTING_FRAME, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.SELECTING_FRAME: {SessionStatus.PROCESSING, SessionStatus.RECAPTURE, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.PROCESSING: {SessionStatus.WAIT_CONFIRM, SessionStatus.RECAPTURE, SessionStatus.NEED_INPUT, SessionStatus.BLOCKED, SessionStatus.FAILED, SessionStatus.CANCELLED},
    SessionStatus.WAIT_CONFIRM: {SessionStatus.EXECUTING, SessionStatus.CANCELLED},
    SessionStatus.EXECUTING: {SessionStatus.SUCCESS, SessionStatus.FAILED},
    SessionStatus.SUCCESS: {SessionStatus.EXECUTING},
    SessionStatus.RECAPTURE: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.NEED_INPUT: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.BLOCKED: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.FAILED: {SessionStatus.CAPTURING, SessionStatus.CANCELLED},
    SessionStatus.CANCELLED: {SessionStatus.CAPTURING},
}


class GlanceFlowSessionService:
    """Orchestrates the simulator; calendar access stays inside TrustedSchedulingService."""

    def __init__(
        self,
        capture_provider: FrameCapturePort,
        frame_selector: DeterministicFrameSelector,
        motion_provider: MotionProvider,
        scheduling_service: TrustedSchedulingService,
    ) -> None:
        self.capture_provider = capture_provider
        self.frame_selector = frame_selector
        self.motion_provider = motion_provider
        self.scheduling_service = scheduling_service
        self._sessions: dict[str, GlanceFlowSession] = {}

    def create_session(self, session_id: str | None = None) -> GlanceFlowSession:
        identifier = session_id or f"GF-SESSION-{uuid4().hex}"
        if identifier in self._sessions:
            raise SessionValidationError("session_id 已存在。")
        now = datetime.now(timezone.utc)
        session = GlanceFlowSession(session_id=identifier, created_at=now, updated_at=now)
        self._sessions[identifier] = session
        self._audit(session, "SESSION_CREATED", "已创建本地模拟会话。")
        return session.model_copy(deep=True)

    def handle_voice_command(
        self,
        session_id: str,
        raw_text: str,
        *,
        confidence: float,
        captured_at: datetime,
        source: str = "text-fallback",
        capture_request: CaptureRequest | None = None,
    ) -> GlanceFlowSession:
        session = self._session(session_id)
        event = interpret_voice(raw_text, confidence=confidence, captured_at=captured_at, source=source, session_id=session_id)
        session.last_voice_event = event
        self._audit(session, "VOICE_INTERPRETED", "语音指令已确定性解析。", intent=event.intent.value, confidence=confidence)
        if event.intent is VoiceIntent.UNKNOWN:
            return session.model_copy(deep=True)
        if event.intent is VoiceIntent.ARRANGE:
            if capture_request is None:
                self._audit(session, "CAPTURE_NOT_STARTED", "缺少短视频输入，未开始采集。")
                return session.model_copy(deep=True)
            return self.start_capture(session_id, capture_request)
        if event.intent is VoiceIntent.CONFIRM:
            confirmation_event = StructuredConfirmationEvent(
                raw_text=raw_text, normalized_text=event.normalized_text, confidence=confidence,
                captured_at=captured_at, source=source, session_id=session_id,
                accepted_conflict=bool(session.preflight_result and session.preflight_result.requires_conflict_confirmation),
            )
            if session.undo_confirmation_pending:
                return self.confirm_undo(session_id, confirmation_event)
            return self.confirm(session_id, confirmation_event)
        if event.intent is VoiceIntent.CANCEL:
            if session.undo_confirmation_pending:
                return self.cancel_undo(session_id)
            return self.cancel(session_id)
        return self.request_undo(session_id)

    def start_capture(self, session_id: str, request: CaptureRequest) -> GlanceFlowSession:
        session = self._session(session_id)
        if request.session_id != session_id:
            raise SessionValidationError("采集请求与会话不匹配。")
        session.cancellation_requested = False
        self._transition(session, SessionStatus.CAPTURING, "CAPTURE_STARTED", "明确触发后开始短时采集。")
        try:
            session.capture_result = self.capture_provider.capture(request)
        except CaptureError as exc:
            self._transition(session, SessionStatus.FAILED, "CAPTURE_FAILED", str(exc))
            return session.model_copy(deep=True)
        if self._cancel_if_requested(session):
            return session.model_copy(deep=True)
        return self.process_capture(session_id, captured_at=session.last_voice_event.captured_at if session.last_voice_event else datetime.now(timezone.utc))

    def process_capture(self, session_id: str, *, captured_at: datetime) -> GlanceFlowSession:
        session = self._session(session_id)
        if session.capture_result is None:
            raise SessionValidationError("没有可处理的采集结果。")
        if self._cancel_if_requested(session):
            return session.model_copy(deep=True)
        self._transition(session, SessionStatus.SELECTING_FRAME, "FRAME_SELECTION_STARTED", "开始自动评估采样帧。")
        session.selection_result = self.frame_selector.select(session.capture_result)
        if self._cancel_if_requested(session):
            return session.model_copy(deep=True)
        selected_id = session.selection_result.selected_frame_id
        self.capture_provider.discard_unselected(session.capture_result, selected_id)
        if session.selection_result.requires_recapture or session.selection_result.selected_image_path is None:
            self._transition(session, SessionStatus.RECAPTURE, "FRAME_SELECTION_REJECTED", session.selection_result.reason)
            return session.model_copy(deep=True)
        self._transition(session, SessionStatus.PROCESSING, "FRAME_SELECTED", session.selection_result.reason, frame_id=selected_id)
        session.pipeline_result = process_image(session.selection_result.selected_image_path, captured_at)
        if self._cancel_if_requested(session):
            return session.model_copy(deep=True)
        result = session.pipeline_result
        if result.final_status is SafetyGateStatus.RECAPTURE_REQUIRED:
            self._transition(session, SessionStatus.RECAPTURE, "PIPELINE_RECAPTURE", "质量或证据不足，未进入确认。")
        elif result.final_status is SafetyGateStatus.NEED_USER_INPUT:
            self._transition(session, SessionStatus.NEED_INPUT, "PIPELINE_NEEDS_INPUT", "结构化信息不完整，未进入确认。")
        elif result.final_status is SafetyGateStatus.CONTRADICTION_BLOCKED:
            self._transition(session, SessionStatus.BLOCKED, "PIPELINE_BLOCKED", "安全门发现确定性矛盾。")
        elif result.extraction_result and result.extraction_result.draft and result.safety_decision:
            try:
                session.preflight_result = self.scheduling_service.preflight(result.extraction_result.draft, result.safety_decision)
                session.transaction_id = session.preflight_result.transaction_id
                if not session.preflight_result.passed:
                    self._transition(session, SessionStatus.BLOCKED, "PREFLIGHT_DUPLICATE_BLOCKED", "发现疑似重复日程，未进入确认。")
                else:
                    session.motion_state = self.motion_provider.get_motion_state(session_id)
                    self._transition(session, SessionStatus.WAIT_CONFIRM, "WAITING_CONFIRMATION", "草案与日历预检完成，等待明确确认。", motion_state=session.motion_state.value)
            except SchedulingValidationError as exc:
                self._transition(session, SessionStatus.FAILED, "PREFLIGHT_FAILED", str(exc))
        else:
            self._transition(session, SessionStatus.FAILED, "PIPELINE_FAILED", "处理结果不完整。")
        return session.model_copy(deep=True)

    def confirm(self, session_id: str, event: StructuredConfirmationEvent) -> GlanceFlowSession:
        session = self._session(session_id)
        if session.status is not SessionStatus.WAIT_CONFIRM or not session.transaction_id:
            raise SessionValidationError("当前会话不允许确认。")
        session.motion_state = self.motion_provider.get_motion_state(session_id)
        if session.motion_state is not MotionState.STATIONARY:
            self._audit(session, "CONFIRMATION_DEFERRED_FOR_MOTION", "移动或姿态未知时禁止日历写入。", motion_state=session.motion_state.value)
            return session.model_copy(deep=True)
        if event.confidence < 0.72:
            self._audit(session, "CONFIRMATION_IGNORED", "确认置信度不足，未执行写入。")
            return session.model_copy(deep=True)
        record = self.scheduling_service.get_transaction(session.transaction_id)
        main = next(item for item in record.planned_requests if item.event_role is EventRole.MAIN_EVENT)
        deadline = next((item for item in record.planned_requests if item.event_role is EventRole.DEADLINE_EVENT), None)
        confirmation = UserConfirmation(
            confirmed=True,
            confirmed_at=event.captured_at,
            confirmed_title=main.title,
            confirmed_event_start=main.start_time,
            confirmed_location=main.location,
            confirmed_deadline=deadline.start_time if deadline else None,
            confirmed_calendar_id=record.calendar_id,
            confirmed_request_hash=calendar_request_digest(record.planned_requests),
            accepted_conflict=event.accepted_conflict,
            confirmation_source=event.source,
        )
        try:
            self.scheduling_service.confirm(session.transaction_id, confirmation)
        except SchedulingValidationError as exc:
            self._audit(session, "CONFIRMATION_REJECTED", str(exc))
            return session.model_copy(deep=True)
        self._transition(session, SessionStatus.EXECUTING, "EXECUTION_STARTED", "确认有效，开始可信事务。")
        session.transaction = self.scheduling_service.execute(session.transaction_id)
        if session.transaction.status is TransactionStatus.VERIFIED:
            session.last_successful_transaction_id = session.transaction_id
            self._transition(session, SessionStatus.SUCCESS, "READBACK_VERIFIED", "事件已创建并通过回读核验。", event_ids=session.transaction.created_event_ids)
        else:
            self._transition(session, SessionStatus.FAILED, "EXECUTION_FAILED", "事务未能完成，已执行安全回滚。", transaction_status=session.transaction.status.value)
        return session.model_copy(deep=True)

    def cancel(self, session_id: str) -> GlanceFlowSession:
        session = self._session(session_id)
        if session.status in {SessionStatus.EXECUTING, SessionStatus.SUCCESS}:
            raise SessionValidationError("已执行的事务不能用取消代替撤销。")
        if session.status in {SessionStatus.CAPTURING, SessionStatus.SELECTING_FRAME, SessionStatus.PROCESSING}:
            session.cancellation_requested = True
            self._audit(session, "CANCELLATION_REQUESTED", "已请求取消；当前本地步骤结束后停止，不会进入日历预检。")
            return session.model_copy(deep=True)
        self._transition(session, SessionStatus.CANCELLED, "SESSION_CANCELLED", "用户取消，未创建事件。")
        return session.model_copy(deep=True)

    def request_undo(self, session_id: str) -> GlanceFlowSession:
        session = self._session(session_id)
        if session.status is not SessionStatus.SUCCESS or not session.last_successful_transaction_id:
            raise SessionValidationError("没有可撤销的成功事务。")
        if session.transaction and session.transaction.status is TransactionStatus.UNDONE:
            raise SessionValidationError("最近事务已经撤销。")
        session.undo_confirmation_pending = True
        session.pending_undo_transaction_id = session.last_successful_transaction_id
        self._audit(
            session,
            "UNDO_CONFIRMATION_REQUESTED",
            "撤销会删除刚创建的日程；等待独立的明确确认。",
            transaction_id=session.pending_undo_transaction_id,
        )
        return session.model_copy(deep=True)

    def undo_last(self, session_id: str) -> GlanceFlowSession:
        """Compatibility entry point: request undo without performing a write."""
        return self.request_undo(session_id)

    def confirm_undo(self, session_id: str, event: StructuredConfirmationEvent) -> GlanceFlowSession:
        session = self._session(session_id)
        transaction_id = session.pending_undo_transaction_id
        if (
            session.status is not SessionStatus.SUCCESS
            or not session.undo_confirmation_pending
            or not transaction_id
        ):
            raise SessionValidationError("当前会话没有等待确认的撤销操作。")
        if event.session_id != session_id:
            raise SessionValidationError("撤销确认与会话不匹配。")
        if transaction_id != session.last_successful_transaction_id:
            session.undo_confirmation_pending = False
            session.pending_undo_transaction_id = None
            self._audit(session, "UNDO_CONFIRMATION_INVALIDATED", "目标事务发生变化，原撤销确认已失效。")
            return session.model_copy(deep=True)
        session.motion_state = self.motion_provider.get_motion_state(session_id)
        if session.motion_state is not MotionState.STATIONARY:
            self._audit(session, "UNDO_DEFERRED_FOR_MOTION", "移动或姿态未知时禁止日历写入。")
            return session.model_copy(deep=True)
        if event.confidence < 0.72:
            self._audit(session, "UNDO_CONFIRMATION_IGNORED", "撤销确认置信度不足，未删除日程。")
            return session.model_copy(deep=True)
        self._transition(session, SessionStatus.EXECUTING, "UNDO_STARTED", "按事务 event_id 精准撤销。")
        session.transaction = self.scheduling_service.undo(transaction_id)
        session.undo_confirmation_pending = False
        session.pending_undo_transaction_id = None
        self._transition(session, SessionStatus.SUCCESS, "UNDO_VERIFIED", "事件已删除并验证不存在。")
        return session.model_copy(deep=True)

    def cancel_undo(self, session_id: str) -> GlanceFlowSession:
        session = self._session(session_id)
        if session.status is not SessionStatus.SUCCESS or not session.undo_confirmation_pending:
            raise SessionValidationError("当前会话没有等待确认的撤销操作。")
        session.undo_confirmation_pending = False
        session.pending_undo_transaction_id = None
        self._audit(session, "UNDO_CANCELLED", "已取消撤销；刚创建的日程保持不变。")
        return session.model_copy(deep=True)

    def get_hud(self, session_id: str) -> HudState:
        return build_hud(self._session(session_id))

    def set_motion_state(self, session_id: str, state: MotionState) -> GlanceFlowSession:
        session = self._session(session_id)
        if hasattr(self.motion_provider, "set_motion_state"):
            self.motion_provider.set_motion_state(session_id, state)
        session.motion_state = state
        self._audit(session, "MOTION_STATE_UPDATED", "模拟姿态状态已更新。", motion_state=state.value)
        return session.model_copy(deep=True)

    def get_session(self, session_id: str) -> GlanceFlowSession:
        return self._session(session_id).model_copy(deep=True)

    def clear_session(self, session_id: str) -> None:
        self._session(session_id)
        self.capture_provider.clear_session(session_id)
        del self._sessions[session_id]

    def _session(self, session_id: str) -> GlanceFlowSession:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionValidationError(f"未知会话：{session_id}") from exc

    def _cancel_if_requested(self, session: GlanceFlowSession) -> bool:
        if not session.cancellation_requested:
            return False
        if session.capture_result:
            self.capture_provider.discard_unselected(session.capture_result, None)
        self._transition(session, SessionStatus.CANCELLED, "SESSION_CANCELLED", "采集或处理已取消，未进入日历事务。")
        return True

    def _transition(self, session: GlanceFlowSession, status: SessionStatus, action: str, message: str, **details) -> None:
        if status not in _ALLOWED.get(session.status, set()):
            raise SessionValidationError(f"非法状态转换：{session.status.value} -> {status.value}")
        session.status = status
        self._audit(session, action, message, **details)

    @staticmethod
    def _audit(session: GlanceFlowSession, action: str, message: str, **details) -> None:
        now = datetime.now(timezone.utc)
        session.updated_at = now
        session.audit_events.append(SessionAuditEvent(occurred_at=now, action=action, message=message, details=details))
