from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from glanceflow.application.glanceflow_service import GlanceFlowSessionService
from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.wearable.capture import FileVideoCaptureProvider
from glanceflow.wearable.frame_selection import DeterministicFrameSelector
from glanceflow.wearable.models import CaptureRequest, MotionState
from glanceflow.wearable.motion import ManualMotionProvider


CAPTURED_AT = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
VIDEO_ROOT = Path("data") / "synthetic_videos"
CAPTURE_ROOT = Path("work") / "wearable-captures"


def _new_service(motion: MotionState = MotionState.STATIONARY):
    provider = MemoryCalendarProvider()
    motion_provider = ManualMotionProvider(motion)
    service = GlanceFlowSessionService(
        FileVideoCaptureProvider(),
        DeterministicFrameSelector(),
        motion_provider,
        TrustedSchedulingService(provider),
    )
    return service, motion_provider, provider


def _arrange(service: GlanceFlowSessionService, name: str, video: str):
    session = service.create_session(f"GF-DEMO-{name}")
    return service.handle_voice_command(
        session.session_id,
        "帮我安排",
        confidence=1.0,
        captured_at=CAPTURED_AT,
        source="wearable-demo",
        capture_request=CaptureRequest(
            session_id=session.session_id,
            video_path=VIDEO_ROOT / video,
            output_dir=CAPTURE_ROOT,
            delete_source_after_processing=False,
        ),
    )


def _confirm(service: GlanceFlowSessionService, session_id: str):
    return service.handle_voice_command(
        session_id,
        "确认",
        confidence=1.0,
        captured_at=CAPTURED_AT + timedelta(minutes=1),
        source="wearable-demo",
    )


def _external_conflict() -> CreateEventRequest:
    start = datetime(2026, 8, 7, 14, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    return CreateEventRequest(
        title="用户已有课程",
        start_time=start,
        end_time=start + timedelta(hours=1),
        timezone="Asia/Shanghai",
        location="教学楼101",
        description="预置外部事件；见程不会修改它。",
        private_metadata={"notice_package_id":"external-demo","transaction_id":"external-demo","event_role":"MAIN_EVENT"},
        notice_package_id="external-demo",
        transaction_id="external-demo",
        event_role=EventRole.MAIN_EVENT,
    )


def _snapshot(service, session_id, provider):
    session = service.get_session(session_id)
    created_ids = set(session.transaction.created_event_ids) if session.transaction else set()
    return {
        "session": session.model_dump(mode="json"),
        "hud": service.get_hud(session_id).model_dump(mode="json"),
        "calendar_event_ids": provider.event_ids,
        "calendar_event_count": provider.event_count,
        "active_glanceflow_event_count": len(created_ids.intersection(provider.event_ids)),
    }


def run_wearable_demo() -> dict:
    normal_service, _, normal_provider = _new_service()
    normal_waiting = _arrange(normal_service, "NORMAL", "04_event_with_deadline.mp4")
    normal_success = _confirm(normal_service, normal_waiting.session_id)
    normal_snapshot = _snapshot(normal_service, normal_success.session_id, normal_provider)
    normal_service.handle_voice_command(
        normal_success.session_id, "撤销上一步", confidence=1.0,
        captured_at=CAPTURED_AT + timedelta(minutes=2), source="wearable-demo",
    )
    normal_service.handle_voice_command(
        normal_success.session_id, "确认", confidence=1.0,
        captured_at=CAPTURED_AT + timedelta(minutes=3), source="wearable-demo",
    )
    undo_snapshot = _snapshot(normal_service, normal_success.session_id, normal_provider)

    blur_service, _, blur_provider = _new_service()
    blur = _arrange(blur_service, "BLUR", "03_always_blurred.mp4")

    blocked_service, _, blocked_provider = _new_service()
    blocked = _arrange(blocked_service, "CONTRADICTION", "05_weekday_contradiction.mp4")

    conflict_service, _, conflict_provider = _new_service()
    conflict_provider.create_event(_external_conflict(), "external-demo")
    conflict = _arrange(conflict_service, "CONFLICT", "01_clear_notice.mp4")

    moving_service, _, moving_provider = _new_service(MotionState.MOVING)
    moving = _arrange(moving_service, "MOVING", "08_moving_notice.mp4")
    moving_after_confirm = _confirm(moving_service, moving.session_id)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "本地第一视角眼镜交互模拟；未部署到真实眼镜设备。",
        "provider": "memory-calendar",
        "privacy": "明确触发后仅处理最多3秒；上传临时视频默认删除；仅保留自动选中的证据帧直至清除会话。",
        "scenarios": {
            "normal_create_verified": normal_snapshot,
            "blur_requires_recapture": _snapshot(blur_service, blur.session_id, blur_provider),
            "contradiction_blocked": _snapshot(blocked_service, blocked.session_id, blocked_provider),
            "conflict_waits_for_secondary_confirmation": _snapshot(conflict_service, conflict.session_id, conflict_provider),
            "moving_confirmation_deferred": _snapshot(moving_service, moving_after_confirm.session_id, moving_provider),
            "undo_last_verified": undo_snapshot,
        },
    }
