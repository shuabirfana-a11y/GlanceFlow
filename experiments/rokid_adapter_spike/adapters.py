from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from PIL import Image

from glanceflow.wearable.models import SampledFrame


class AdapterError(RuntimeError):
    pass


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"


@dataclass(frozen=True)
class DeviceImage:
    content: bytes
    captured_at: datetime
    frame_id: str
    media_type: str = "image/png"


@dataclass(frozen=True)
class VoiceCommand:
    text: str
    captured_at: datetime
    command_id: str


@dataclass(frozen=True)
class HudMessage:
    message_id: str
    headline: str
    body: str
    severity: str = "INFO"


class CameraAdapter(Protocol):
    def capture(self) -> DeviceImage: ...


class VoiceAdapter(Protocol):
    def receive_command(self) -> VoiceCommand | None: ...


class HUDAdapter(Protocol):
    def show(self, message: HudMessage) -> None: ...


class DeviceConnectionAdapter(Protocol):
    @property
    def state(self) -> ConnectionState: ...

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...


class VisionAdapter(Protocol):
    def recognize(self, image: bytes): ...

    def healthcheck(self) -> bool: ...

    def get_version(self) -> str: ...

    def get_capabilities(self) -> set[str]: ...


class FakeRokidAdapter:
    """Deterministic fake bridge. It contains no Rokid SDK code or network I/O."""

    def __init__(self, *, image: bytes, voice_commands: list[VoiceCommand] | None = None):
        self._image = image
        self._voice_commands = list(voice_commands or [])
        self._state = ConnectionState.DISCONNECTED
        self.hud_messages: list[HudMessage] = []
        self.fail_hud = False

    @property
    def state(self) -> ConnectionState:
        return self._state

    def connect(self) -> None:
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    def disconnect(self) -> None:
        self._state = ConnectionState.DISCONNECTED

    def capture(self) -> DeviceImage:
        self._require_connected()
        try:
            with Image.open(io.BytesIO(self._image)) as image:
                image.verify()
        except Exception as exc:
            raise AdapterError("device returned invalid image bytes") from exc
        digest = hashlib.sha256(self._image).hexdigest()[:16]
        return DeviceImage(
            content=self._image,
            captured_at=datetime.now().astimezone(),
            frame_id=f"fake-rokid-{digest}",
        )

    def receive_command(self) -> VoiceCommand | None:
        self._require_connected()
        return self._voice_commands.pop(0) if self._voice_commands else None

    def show(self, message: HudMessage) -> None:
        self._require_connected()
        if self.fail_hud:
            raise AdapterError("fake HUD delivery failed")
        self.hud_messages.append(message)

    def encode_hud_message(self, message: HudMessage) -> bytes:
        return json.dumps(
            {
                "type": "HUD_MESSAGE",
                "message_id": message.message_id,
                "headline": message.headline,
                "body": message.body,
                "severity": message.severity,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _require_connected(self) -> None:
        if self._state is not ConnectionState.CONNECTED:
            raise AdapterError("device bridge is disconnected")


def to_glanceflow_sampled_frame(device_image: DeviceImage, output_dir: Path) -> SampledFrame:
    """Boundary conversion; core wearable models stay unaware of Rokid."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{device_image.frame_id}.png"
    try:
        with Image.open(io.BytesIO(device_image.content)) as source:
            source.load()
            converted = source.convert("RGB")
            converted.save(path, format="PNG")
            width, height = converted.size
    except Exception as exc:
        raise AdapterError("cannot convert device image to GlanceFlow capture input") from exc
    return SampledFrame(
        frame_id=device_image.frame_id,
        timestamp_ms=0,
        image_path=path,
        width=width,
        height=height,
        file_size_bytes=path.stat().st_size,
    )
