from glanceflow.device.errors import DeviceUnavailableError
from glanceflow.device.models import DeviceCapabilities, HUDMessage
from glanceflow.device.rokid.config import RokidAdapterConfig


class RokidSDKUnavailableAdapter:
    """Honest boundary placeholder; it contains no invented SDK calls."""

    def __init__(self, config: RokidAdapterConfig | None = None) -> None:
        self.config = config or RokidAdapterConfig()

    def connect(self) -> None:
        raise DeviceUnavailableError("SDK_UNAVAILABLE")

    def disconnect(self) -> None: pass
    def healthcheck(self) -> bool: return False
    def get_capabilities(self) -> DeviceCapabilities: return DeviceCapabilities()
    def capture(self): raise DeviceUnavailableError("SDK_UNAVAILABLE")
    def next_command(self): raise DeviceUnavailableError("SDK_UNAVAILABLE")
    def display(self, message: HUDMessage) -> None: raise DeviceUnavailableError("SDK_UNAVAILABLE")
    def clear(self) -> None: raise DeviceUnavailableError("SDK_UNAVAILABLE")
