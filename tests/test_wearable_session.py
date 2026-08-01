import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import glanceflow.application.glanceflow_service as service_module
from glanceflow.application.glanceflow_service import GlanceFlowSessionService, SessionValidationError
from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import CreateEventRequest, EventRole
from glanceflow.pipeline import ImagePipelineResult
from glanceflow.wearable.models import CaptureRequest, CaptureResult, FrameSelectionResult, MotionState, SampledFrame, SessionStatus
from glanceflow.wearable.motion import ManualMotionProvider


NOW = datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))


def load_result(filename):
    data = json.loads(Path("outputs/stage2_results.json").read_text(encoding="utf-8"))
    return ImagePipelineResult.model_validate(next(x["result"] for x in data if Path(x["source_file"]).name == filename))


class FakeCapture:
    def __init__(self, selected=Path("data/synthetic_posters/01_valid_event.png")):
        self.selected = selected; self.discarded = False; self.cleared = False
    def capture(self, request):
        return CaptureResult(session_id=request.session_id, source_video_name=request.video_path.name, sampled_frames=[SampledFrame(frame_id="auto-frame", timestamp_ms=500, image_path=self.selected, width=1400, height=900, file_size_bytes=self.selected.stat().st_size)], source_duration_ms=1000, captured_duration_ms=1000, raw_video_deleted=True)
    def discard_unselected(self, result, selected_frame_id): self.discarded = True
    def clear_session(self, session_id): self.cleared = True


class FakeSelector:
    def __init__(self, path=Path("data/synthetic_posters/01_valid_event.png"), reject=False): self.path=path; self.reject=reject
    def select(self, capture):
        return FrameSelectionResult(selected_frame_id=None if self.reject else "auto-frame", selected_image_path=None if self.reject else self.path, requires_recapture=self.reject, reason="无合格帧" if self.reject else "自动选择")


def make_service(monkeypatch, filename="01_valid_event.png", motion=MotionState.STATIONARY, reject=False):
    result = load_result(filename); monkeypatch.setattr(service_module, "process_image", lambda *args, **kwargs: result)
    motion_provider=ManualMotionProvider(motion)
    provider=MemoryCalendarProvider()
    service=GlanceFlowSessionService(FakeCapture(), FakeSelector(reject=reject), motion_provider, TrustedSchedulingService(provider))
    return service, motion_provider, provider


def arrange(service, sid):
    return service.handle_voice_command(sid, "帮我安排", confidence=1, captured_at=NOW, capture_request=CaptureRequest(session_id=sid, video_path=Path("fake.mp4"), output_dir=Path("work"), delete_source_after_processing=False))


def test_normal_flow_confirmation_readback_and_undo(monkeypatch):
    service, _, provider = make_service(monkeypatch, "02_event_with_deadline.png")
    sid=service.create_session("normal").session_id
    waiting=arrange(service,sid); assert waiting.status is SessionStatus.WAIT_CONFIRM; assert provider.event_count == 0
    success=service.handle_voice_command(sid,"确认",confidence=1,captured_at=NOW); assert success.status is SessionStatus.SUCCESS; assert provider.event_count == 2
    undone=service.handle_voice_command(sid,"撤销上一步",confidence=1,captured_at=NOW); assert undone.transaction.status.value == "UNDONE"; assert provider.event_count == 0


@pytest.mark.parametrize(("filename","status"), [("03_weekday_contradiction.png",SessionStatus.BLOCKED),("04_unresolved_time.png",SessionStatus.NEED_INPUT)])
def test_safety_states_never_create_events(monkeypatch, filename, status):
    service,_,provider=make_service(monkeypatch,filename); sid=service.create_session().session_id
    assert arrange(service,sid).status is status
    assert provider.event_count == 0


def test_moving_or_unknown_cannot_confirm(monkeypatch):
    service,motion,provider=make_service(monkeypatch,motion=MotionState.MOVING); sid=service.create_session().session_id; arrange(service,sid)
    assert service.handle_voice_command(sid,"确认",confidence=1,captured_at=NOW).status is SessionStatus.WAIT_CONFIRM
    assert provider.event_count == 0; assert service.get_hud(sid).headline == "请先停稳"
    motion.set_motion_state(sid,MotionState.STATIONARY)
    assert service.handle_voice_command(sid,"确认",confidence=1,captured_at=NOW).status is SessionStatus.SUCCESS


def test_cancel_and_low_confidence_create_nothing(monkeypatch):
    service,_,provider=make_service(monkeypatch); sid=service.create_session().session_id; arrange(service,sid)
    assert service.handle_voice_command(sid,"确认",confidence=.2,captured_at=NOW).status is SessionStatus.WAIT_CONFIRM
    assert service.handle_voice_command(sid,"取消",confidence=1,captured_at=NOW).status is SessionStatus.CANCELLED
    assert provider.event_count == 0


def test_no_eligible_frame_recaptures_without_ocr_pipeline(monkeypatch):
    service,_,provider=make_service(monkeypatch,reject=True); sid=service.create_session().session_id
    assert arrange(service,sid).status is SessionStatus.RECAPTURE; assert provider.event_count == 0


def test_invalid_transition_and_clear(monkeypatch):
    service,_,_=make_service(monkeypatch); sid=service.create_session().session_id
    with pytest.raises(SessionValidationError): service.confirm(sid,None)
    service.clear_session(sid)
    with pytest.raises(SessionValidationError): service.get_session(sid)


def test_conflict_without_explicit_confirmation_creates_no_new_event(monkeypatch):
    service,_,provider=make_service(monkeypatch)
    draft=load_result("01_valid_event.png").extraction_result.draft
    start=draft.main_event.event_start
    provider.create_event(CreateEventRequest(
        title="已有课程",start_time=start,end_time=start.replace(hour=start.hour+1),timezone=draft.timezone,
        location="教学楼",description="外部事件",private_metadata={"notice_package_id":"external","transaction_id":"external","event_role":"MAIN_EVENT"},
        notice_package_id="external",transaction_id="external",event_role=EventRole.MAIN_EVENT,
    ),"external")
    sid=service.create_session().session_id
    waiting=arrange(service,sid)
    assert waiting.preflight_result.requires_conflict_confirmation
    assert waiting.status is SessionStatus.WAIT_CONFIRM
    assert provider.event_count == 1
    assert waiting.transaction is None


@pytest.mark.parametrize("fault", [MemoryFaultPlan(fail_create_on_calls={2}), MemoryFaultPlan(tamper_readback_by_role={"MAIN_EVENT":{"title":"错误标题"}})])
def test_transaction_failure_never_reports_success(monkeypatch, fault):
    result=load_result("02_event_with_deadline.png"); monkeypatch.setattr(service_module,"process_image",lambda *args,**kwargs:result)
    provider=MemoryCalendarProvider(fault)
    service=GlanceFlowSessionService(FakeCapture(),FakeSelector(),ManualMotionProvider(MotionState.STATIONARY),TrustedSchedulingService(provider))
    sid=service.create_session().session_id; arrange(service,sid)
    failed=service.handle_voice_command(sid,"确认",confidence=1,captured_at=NOW)
    assert failed.status is SessionStatus.FAILED
    assert provider.event_count == 0


def test_duplicate_preflight_is_blocked_not_confirmable(monkeypatch):
    service,_,provider=make_service(monkeypatch)
    first=service.create_session("first").session_id; arrange(service,first); service.handle_voice_command(first,"确认",confidence=1,captured_at=NOW)
    second=service.create_session("second").session_id
    duplicate=arrange(service,second)
    assert duplicate.status is SessionStatus.BLOCKED
    assert duplicate.preflight_result.passed is False
    assert provider.event_count == 1


def test_cancel_during_capture_stops_before_calendar(monkeypatch):
    result=load_result("01_valid_event.png"); monkeypatch.setattr(service_module,"process_image",lambda *args,**kwargs:result)
    started=threading.Event(); release=threading.Event()
    class BlockingCapture(FakeCapture):
        def capture(self, request):
            started.set(); release.wait(timeout=5); return super().capture(request)
    provider=MemoryCalendarProvider()
    service=GlanceFlowSessionService(BlockingCapture(),FakeSelector(),ManualMotionProvider(MotionState.STATIONARY),TrustedSchedulingService(provider))
    sid=service.create_session().session_id
    with ThreadPoolExecutor(max_workers=1) as executor:
        future=executor.submit(arrange,service,sid)
        assert started.wait(timeout=2)
        pending=service.handle_voice_command(sid,"取消",confidence=1,captured_at=NOW)
        assert pending.cancellation_requested
        release.set(); cancelled=future.result(timeout=5)
    assert cancelled.status is SessionStatus.CANCELLED
    assert provider.event_count == 0
    assert cancelled.preflight_result is None
