from __future__ import annotations

from collections import deque

from glanceflow.device.errors import DeviceUnavailableError
from glanceflow.device.models import CapturedImage, ConnectionState, DeviceCapabilities, HUDMessage, VoiceCommand


class FakeDeviceAdapter:
    def __init__(
        self,
        *,
        images: list[CapturedImage] | None = None,
        commands: list[VoiceCommand] | None = None,
        capabilities: DeviceCapabilities | None = None,
    ) -> None:
        self.images = deque(images or [])
        self.commands = deque(commands or [])
        self.messages: list[HUDMessage] = []
        self.state = ConnectionState.DISCONNECTED
        self.fail_capture = False
        self.fail_hud = False
        self.capabilities = capabilities or DeviceCapabilities(
            camera=True, microphone=True, hud=True, still_capture=True, voice_text=True
        )

    def connect(self) -> None:
        self.state = ConnectionState.CONNECTED

    def disconnect(self) -> None:
        self.state = ConnectionState.DISCONNECTED

    def healthcheck(self) -> bool:
        return self.state is ConnectionState.CONNECTED

    def get_capabilities(self) -> DeviceCapabilities:
        return self.capabilities

    def capture(self) -> CapturedImage:
        self._available()
        if self.fail_capture or not self.images:
            raise DeviceUnavailableError("fake camera unavailable")
        return self.images.popleft()

    def next_command(self) -> VoiceCommand | None:
        self._available()
        return self.commands.popleft() if self.commands else None

    def display(self, message: HUDMessage) -> None:
        self._available()
        if self.fail_hud:
            raise DeviceUnavailableError("fake HUD unavailable")
        self.messages.append(message)

    def clear(self) -> None:
        self._available()
        self.messages.clear()

    def _available(self) -> None:
        if self.state is not ConnectionState.CONNECTED:
            raise DeviceUnavailableError("fake device disconnected")
