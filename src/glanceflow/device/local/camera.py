from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from glanceflow.device.errors import DeviceUnavailableError
from glanceflow.device.models import CapturedImage, DeviceCapabilities, DeviceSourceType, TimestampSource


class LocalFileCameraAdapter:
    """Runnable file-upload fallback; no webcam is opened implicitly."""

    def __init__(self, image_path: Path, *, device_name: str = "local-file-upload") -> None:
        self.image_path = Path(image_path)
        self.device_name = device_name
        self.connected = False
        self.sequence = 0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def healthcheck(self) -> bool:
        return self.connected and self.image_path.is_file()

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(camera=True, still_capture=True)

    def capture(self) -> CapturedImage:
        if not self.healthcheck():
            raise DeviceUnavailableError("local image file unavailable")
        content = self.image_path.read_bytes()
        try:
            with Image.open(self.image_path) as image:
                width, height = image.size
                mime = "image/png" if image.format == "PNG" else "image/jpeg"
        except Exception as exc:
            raise DeviceUnavailableError("local image is invalid") from exc
        now = datetime.now(timezone.utc)
        self.sequence += 1
        capture_id = f"local-capture-{self.sequence}"
        return CapturedImage(
            capture_id=capture_id, captured_at=now, image_bytes=content, mime_type=mime,
            width=width, height=height, source_device=self.device_name,
            source_type=DeviceSourceType.FILE_UPLOAD, sequence_number=self.sequence,
            message_id=capture_id, device_timestamp=None, received_at=now,
            canonical_capture_timestamp=now, timestamp_source=TimestampSource.RECEIVER,
        )
