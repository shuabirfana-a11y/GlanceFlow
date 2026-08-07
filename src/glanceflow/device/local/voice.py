from collections import deque

from glanceflow.device.errors import DeviceUnavailableError
from glanceflow.device.models import VoiceCommand


class LocalTextVoiceAdapter:
    def __init__(self, commands: list[VoiceCommand] | None = None) -> None:
        self.commands = deque(commands or [])
        self.connected = False

    def connect(self) -> None: self.connected = True
    def disconnect(self) -> None: self.connected = False
    def healthcheck(self) -> bool: return self.connected

    def next_command(self) -> VoiceCommand | None:
        if not self.connected:
            raise DeviceUnavailableError("local text input disconnected")
        return self.commands.popleft() if self.commands else None
