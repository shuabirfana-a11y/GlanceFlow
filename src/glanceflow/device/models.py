from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeviceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return value


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"


class TimestampSource(StrEnum):
    DEVICE = "DEVICE"
    RECEIVER = "RECEIVER"
    RECOVERED = "RECOVERED"


class DeviceSourceType(StrEnum):
    ROKID = "ROKID"
    LOCAL = "LOCAL"
    FAKE = "FAKE"
    FILE_UPLOAD = "FILE_UPLOAD"


class HudMessageType(StrEnum):
    INFO = "INFO"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class DeviceCapabilities(DeviceModel):
    camera: bool = False
    microphone: bool = False
    hud: bool = False
    realtime_stream: bool = False
    still_capture: bool = False
    voice_text: bool = False
    max_image_width: int | None = Field(default=None, gt=0)
    max_image_height: int | None = Field(default=None, gt=0)


class CapturedImage(DeviceModel):
    capture_id: str = Field(min_length=1)
    captured_at: datetime
    image_bytes: bytes = Field(min_length=1, repr=False)
    mime_type: str = Field(pattern=r"^image/(png|jpeg)$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    source_device: str = Field(min_length=1)
    source_type: DeviceSourceType
    sequence_number: int = Field(ge=0)
    message_id: str = Field(min_length=1)
    device_timestamp: datetime | None = None
    received_at: datetime
    canonical_capture_timestamp: datetime
    timestamp_source: TimestampSource

    _captured_at = field_validator(
        "captured_at", "device_timestamp", "received_at", "canonical_capture_timestamp"
    )(_aware)

    @model_validator(mode="after")
    def canonical_time_is_capture_time(self) -> "CapturedImage":
        if self.captured_at != self.canonical_capture_timestamp:
            raise ValueError("captured_at must equal canonical_capture_timestamp")
        return self


class VoiceCommand(DeviceModel):
    command_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    captured_at: datetime
    received_at: datetime
    text: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_device: str = Field(min_length=1)
    sequence_number: int = Field(ge=0)

    _timestamps = field_validator("captured_at", "received_at")(_aware)


class HUDMessage(DeviceModel):
    message_id: str = Field(min_length=1)
    created_at: datetime
    message_type: HudMessageType
    title: str = Field(min_length=1, max_length=64)
    body: str = Field(max_length=256)
    requires_response: bool = False
    correlation_id: str | None = None

    _created_at = field_validator("created_at")(_aware)


class DeviceAuditEvent(DeviceModel):
    occurred_at: datetime
    event: str
    message_id: str | None = None
    details: dict[str, str | int | bool | None] = Field(default_factory=dict)

    _occurred_at = field_validator("occurred_at")(_aware)


class DeviceFallback(DeviceModel):
    event: str = "DEVICE_FALLBACK"
    from_adapter: str
    to_adapter: str
    reason: str
    occurred_at: datetime

    _occurred_at = field_validator("occurred_at")(_aware)
