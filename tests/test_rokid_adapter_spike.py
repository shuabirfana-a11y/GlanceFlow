from datetime import datetime, timezone
from io import BytesIO

import pytest
from PIL import Image

from experiments.rokid_adapter_spike.adapters import (
    AdapterError,
    ConnectionState,
    FakeRokidAdapter,
    HudMessage,
    VoiceCommand,
    to_glanceflow_sampled_frame,
)
from glanceflow.wearable.models import SampledFrame


def png_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 18), "white").save(output, format="PNG")
    return output.getvalue()


def connected_fake(**kwargs) -> FakeRokidAdapter:
    adapter = FakeRokidAdapter(image=png_bytes(), **kwargs)
    adapter.connect()
    return adapter


def test_fake_camera_converts_to_existing_capture_contract(tmp_path):
    frame = to_glanceflow_sampled_frame(connected_fake().capture(), tmp_path)
    assert isinstance(frame, SampledFrame)
    assert (frame.width, frame.height) == (32, 18)
    assert frame.image_path.read_bytes().startswith(b"\x89PNG")


def test_fake_voice_adapter_returns_queued_command():
    command = VoiceCommand("安排日程", datetime.now(timezone.utc), "voice-1")
    adapter = connected_fake(voice_commands=[command])
    assert adapter.receive_command() == command
    assert adapter.receive_command() is None


def test_fake_hud_records_and_encodes_device_message():
    adapter = connected_fake()
    message = HudMessage("hud-1", "需要确认", "请核对时间", "WARNING")
    adapter.show(message)
    assert adapter.hud_messages == [message]
    assert b'"type":"HUD_MESSAGE"' in adapter.encode_hud_message(message)


def test_disconnect_blocks_all_device_operations():
    adapter = connected_fake()
    adapter.disconnect()
    assert adapter.state is ConnectionState.DISCONNECTED
    with pytest.raises(AdapterError, match="disconnected"):
        adapter.capture()


def test_reconnect_restores_operations():
    adapter = connected_fake()
    adapter.disconnect()
    adapter.connect()
    assert adapter.capture().content == png_bytes()


def test_bad_image_is_rejected():
    adapter = FakeRokidAdapter(image=b"not-an-image")
    adapter.connect()
    with pytest.raises(AdapterError, match="invalid image"):
        adapter.capture()


def test_hud_failure_is_explicit_and_not_recorded():
    adapter = connected_fake()
    adapter.fail_hud = True
    with pytest.raises(AdapterError, match="HUD delivery failed"):
        adapter.show(HudMessage("hud-2", "失败", "未显示"))
    assert adapter.hud_messages == []
