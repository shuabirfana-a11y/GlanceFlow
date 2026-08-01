from __future__ import annotations

from typing import Protocol

from glanceflow.wearable.models import CaptureRequest, CaptureResult, MotionState


class FrameCapturePort(Protocol):
    def capture(self, request: CaptureRequest) -> CaptureResult: ...

    def discard_unselected(self, result: CaptureResult, selected_frame_id: str | None) -> None: ...

    def clear_session(self, session_id: str) -> None: ...


class MotionProvider(Protocol):
    def get_motion_state(self, session_id: str) -> MotionState: ...
