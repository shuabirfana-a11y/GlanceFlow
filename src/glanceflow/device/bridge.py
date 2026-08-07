from __future__ import annotations

import hashlib
import io
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from glanceflow.device.errors import (
    DeviceSequenceError,
    DuplicateDeviceMessageError,
    InvalidDevicePayloadError,
    StaleDeviceMessageError,
)
from glanceflow.device.models import (
    CapturedImage,
    ConnectionState,
    DeviceAuditEvent,
    DeviceSourceType,
    HUDMessage,
    TimestampSource,
    VoiceCommand,
)
from glanceflow.wearable.models import SampledFrame


class DeviceBridge:
    """Transport reliability only; it never authorizes or performs an action."""

    def __init__(self, *, dedup_window: int = 256, max_packet_age: timedelta = timedelta(minutes=5)):
        self.state = ConnectionState.DISCONNECTED
        self._dedup_window = dedup_window
        self._seen_queue: deque[str] = deque()
        self._seen: set[str] = set()
        self._last_sequence: dict[str, int] = {}
        self._hud_seen: set[str] = set()
        self.max_packet_age = max_packet_age
        self.audit: list[DeviceAuditEvent] = []

    def connect(self) -> None:
        self.state = ConnectionState.CONNECTING
        self.state = ConnectionState.CONNECTED

    def disconnect(self) -> None:
        self.state = ConnectionState.DISCONNECTED

    def reconnect(self) -> None:
        self.state = ConnectionState.RECONNECTING
        self.state = ConnectionState.CONNECTED

    def degrade(self, reason: str) -> None:
        self.state = ConnectionState.DEGRADED
        self._audit("TRANSPORT_DEGRADED", details={"reason": reason})

    def fail(self, reason: str) -> None:
        self.state = ConnectionState.FAILED
        self._audit("TRANSPORT_FAILED", details={"reason": reason})

    def accept_image_packet(
        self,
        *,
        capture_id: str,
        message_id: str,
        image_bytes: bytes,
        mime_type: str,
        source_device: str,
        source_type: DeviceSourceType,
        sequence_number: int,
        received_at: datetime,
        device_timestamp: datetime | None,
    ) -> CapturedImage:
        self._require_connected()
        self._accept_envelope(message_id, source_device, sequence_number, received_at)
        width, height = self._validate_image(image_bytes, mime_type)
        canonical, source = self._canonical_timestamp(device_timestamp, received_at)
        result = CapturedImage(
            capture_id=capture_id,
            captured_at=canonical,
            image_bytes=image_bytes,
            mime_type=mime_type,
            width=width,
            height=height,
            source_device=source_device,
            source_type=source_type,
            sequence_number=sequence_number,
            message_id=message_id,
            device_timestamp=device_timestamp,
            received_at=received_at,
            canonical_capture_timestamp=canonical,
            timestamp_source=source,
        )
        self._audit("IMAGE_ACCEPTED", message_id, {"timestamp_source": source.value})
        return result

    def accept_voice_packet(self, command: VoiceCommand) -> VoiceCommand:
        self._require_connected()
        self._accept_envelope(
            command.message_id, command.source_device, command.sequence_number, command.received_at
        )
        self._audit("VOICE_ACCEPTED", command.message_id)
        return command

    def display_hud_once(self, adapter, message: HUDMessage) -> bool:
        """Deduplicate delivery only; this never records user confirmation."""
        if message.message_id in self._hud_seen:
            self._audit("HUD_DUPLICATE_DROPPED", message.message_id)
            return False
        adapter.display(message)
        self._hud_seen.add(message.message_id)
        self._audit("HUD_DELIVERED", message.message_id)
        return True

    def to_sampled_frame(self, captured: CapturedImage, output_dir: Path) -> SampledFrame:
        digest = hashlib.sha256(captured.image_bytes).hexdigest()
        output_dir.mkdir(parents=True, exist_ok=True)
        extension = ".png" if captured.mime_type == "image/png" else ".jpg"
        path = output_dir / f"{captured.capture_id}-{digest[:12]}{extension}"
        path.write_bytes(captured.image_bytes)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            path.unlink(missing_ok=True)
            raise InvalidDevicePayloadError("persisted image hash differs from received bytes")
        return SampledFrame(
            frame_id=captured.capture_id,
            timestamp_ms=0,
            image_path=path,
            width=captured.width,
            height=captured.height,
            file_size_bytes=len(captured.image_bytes),
        )

    def _accept_envelope(self, message_id: str, source: str, sequence: int, received_at: datetime) -> None:
        now = datetime.now(timezone.utc)
        if now - received_at.astimezone(timezone.utc) > self.max_packet_age:
            raise StaleDeviceMessageError(f"stale device message: {message_id}")
        if message_id in self._seen:
            self._audit("DUPLICATE_DROPPED", message_id)
            raise DuplicateDeviceMessageError(f"duplicate device message: {message_id}")
        last = self._last_sequence.get(source)
        if last is not None and sequence <= last:
            raise DeviceSequenceError(f"out-of-order sequence {sequence}; last accepted {last}")
        self._last_sequence[source] = sequence
        self._remember(message_id)

    def _remember(self, message_id: str) -> None:
        self._seen.add(message_id)
        self._seen_queue.append(message_id)
        while len(self._seen_queue) > self._dedup_window:
            self._seen.discard(self._seen_queue.popleft())

    @staticmethod
    def _canonical_timestamp(device: datetime | None, received: datetime) -> tuple[datetime, TimestampSource]:
        if device is None:
            return received, TimestampSource.RECEIVER
        delta = abs(received.astimezone(timezone.utc) - device.astimezone(timezone.utc))
        if delta > timedelta(minutes=10):
            return received, TimestampSource.RECOVERED
        return device, TimestampSource.DEVICE

    @staticmethod
    def _validate_image(content: bytes, mime_type: str) -> tuple[int, int]:
        if mime_type not in {"image/png", "image/jpeg"}:
            raise InvalidDevicePayloadError("unsupported image MIME type")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
                width, height = image.size
        except Exception as exc:
            raise InvalidDevicePayloadError("corrupted image bytes") from exc
        return width, height

    def _require_connected(self) -> None:
        if self.state not in {ConnectionState.CONNECTED, ConnectionState.DEGRADED}:
            raise InvalidDevicePayloadError(f"device bridge is {self.state.value}")

    def _audit(self, event: str, message_id: str | None = None, details=None) -> None:
        self.audit.append(DeviceAuditEvent(
            occurred_at=datetime.now(timezone.utc), event=event, message_id=message_id, details=details or {}
        ))
