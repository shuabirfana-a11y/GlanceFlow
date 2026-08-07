from glanceflow.device.errors import DeviceUnavailableError
from glanceflow.device.models import HUDMessage


class BrowserHUDAdapter:
    """Local browser-facing sink. Delivery is never a confirmation event."""

    def __init__(self) -> None:
        self.connected = False
        self.current: HUDMessage | None = None

    def connect(self) -> None: self.connected = True
    def disconnect(self) -> None: self.connected = False
    def healthcheck(self) -> bool: return self.connected

    def display(self, message: HUDMessage) -> None:
        if not self.connected:
            raise DeviceUnavailableError("browser HUD disconnected")
        self.current = message

    def clear(self) -> None:
        if not self.connected:
            raise DeviceUnavailableError("browser HUD disconnected")
        self.current = None
