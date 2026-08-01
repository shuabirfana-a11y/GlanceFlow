from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from glanceflow.application.glanceflow_service import GlanceFlowSessionService, SessionValidationError
from glanceflow.wearable.models import CaptureRequest, MotionState


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".avi", ".mov", ".mkv", ".webm"}


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSessionBody(ApiModel):
    motion_state: MotionState = MotionState.STATIONARY


class VoiceBody(ApiModel):
    text: str = Field(min_length=1, max_length=40)
    confidence: float = Field(default=1.0, ge=0, le=1)
    source: str = Field(default="text-fallback", max_length=40)
    motion_state: MotionState | None = None


def build_router(service: GlanceFlowSessionService, upload_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api")

    def response(session_id: str) -> dict:
        return {
            "session": service.get_session(session_id).model_dump(mode="json"),
            "hud": service.get_hud(session_id).model_dump(mode="json"),
        }

    @router.post("/sessions")
    def create_session(body: CreateSessionBody) -> dict:
        session = service.create_session()
        service.set_motion_state(session.session_id, body.motion_state)
        return response(session.session_id)

    @router.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        try:
            return response(session_id)
        except SessionValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/sessions/{session_id}/capture")
    async def capture(
        session_id: str,
        video: UploadFile = File(...),
        command: str = Form("帮我安排"),
        confidence: float = Form(1.0),
        motion_state: MotionState = Form(MotionState.STATIONARY),
    ) -> dict:
        suffix = Path(video.filename or "capture.webm").suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise HTTPException(status_code=415, detail="不支持的视频格式。")
        session_dir = upload_root / Path(session_id).name
        session_dir.mkdir(parents=True, exist_ok=True)
        target = session_dir / f"raw-capture{suffix}"
        total = 0
        try:
            with target.open("wb") as handle:
                while chunk := await video.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="短视频超过 25MB 限制。")
                    handle.write(chunk)
            service.set_motion_state(session_id, motion_state)
            request = CaptureRequest(
                session_id=session_id,
                video_path=target,
                output_dir=Path("work") / "wearable-captures",
                delete_source_after_processing=True,
            )
            await run_in_threadpool(
                service.handle_voice_command,
                session_id,
                command,
                confidence=confidence,
                captured_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                source="browser-speech-or-text",
                capture_request=request,
            )
            return response(session_id)
        except HTTPException:
            target.unlink(missing_ok=True)
            raise
        except SessionValidationError as exc:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            await video.close()

    @router.post("/sessions/{session_id}/voice")
    def voice(session_id: str, body: VoiceBody) -> dict:
        try:
            if body.motion_state is not None:
                service.set_motion_state(session_id, body.motion_state)
            service.handle_voice_command(
                session_id,
                body.text,
                confidence=body.confidence,
                captured_at=datetime.now(ZoneInfo("Asia/Shanghai")),
                source=body.source,
            )
            return response(session_id)
        except SessionValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.delete("/sessions/{session_id}", status_code=204)
    def clear_session(session_id: str) -> None:
        try:
            service.clear_session(session_id)
        except SessionValidationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
