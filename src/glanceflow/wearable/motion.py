from __future__ import annotations

from glanceflow.wearable.models import MotionState


class ManualMotionProvider:
    def __init__(self, default: MotionState = MotionState.UNKNOWN) -> None:
        self.default = default
        self._states: dict[str, MotionState] = {}

    def set_motion_state(self, session_id: str, state: MotionState) -> None:
        self._states[session_id] = state

    def get_motion_state(self, session_id: str) -> MotionState:
        return self._states.get(session_id, self.default)
