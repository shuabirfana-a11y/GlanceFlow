from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from PIL import Image

from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider
from glanceflow.device.bridge import DeviceBridge
from glanceflow.device.errors import (
    DeviceSequenceError,
    DeviceUnavailableError,
    DuplicateDeviceMessageError,
    InvalidDevicePayloadError,
    StaleDeviceMessageError,
)
from glanceflow.device.fake import FakeDeviceAdapter
from glanceflow.device.local import BrowserHUDAdapter, LocalFileCameraAdapter, LocalTextVoiceAdapter
from glanceflow.device.models import (
    CapturedImage,
    ConnectionState,
    DeviceCapabilities,
    DeviceFallback,
    DeviceSourceType,
    HUDMessage,
    HudMessageType,
    TimestampSource,
    VoiceCommand,
)
from glanceflow.device.rokid import RokidSDKUnavailableAdapter
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.pipeline import process_image
from glanceflow.vision import PaddleOCRAdapter, RapidOCRAdapter


ROOT = Path(__file__).resolve().parents[1]
POSTER = ROOT / "data" / "synthetic_posters" / "01_valid_event.png"
POSTER_WITH_DEADLINE = ROOT / "data" / "synthetic_posters" / "02_event_with_deadline.png"
NOW = datetime.now(timezone.utc)


def raw_packet(**changes):
    data = {
        "capture_id": "capture-1", "message_id": "image-message-1",
        "image_bytes": POSTER.read_bytes(), "mime_type": "image/png",
        "source_device": "fake-glasses", "source_type": DeviceSourceType.FAKE,
        "sequence_number": 1, "received_at": NOW, "device_timestamp": NOW,
    }
    data.update(changes)
    return data


def accepted_image(bridge: DeviceBridge | None = None, **changes) -> CapturedImage:
    bridge = bridge or DeviceBridge()
    if bridge.state is ConnectionState.DISCONNECTED:
        bridge.connect()
    return bridge.accept_image_packet(**raw_packet(**changes))


def voice(message="voice-message-1", sequence=1, received=NOW):
    return VoiceCommand(
        command_id="command-1", message_id=message, captured_at=received,
        received_at=received, text="安排一下", confidence=0.98,
        source_device="fake-glasses-voice", sequence_number=sequence,
    )


def test_connection_state_machine_and_reconnect():
    bridge = DeviceBridge()
    assert bridge.state is ConnectionState.DISCONNECTED
    bridge.connect(); assert bridge.state is ConnectionState.CONNECTED
    bridge.degrade("HUD lost"); assert bridge.state is ConnectionState.DEGRADED
    bridge.reconnect(); assert bridge.state is ConnectionState.CONNECTED
    bridge.disconnect(); assert bridge.state is ConnectionState.DISCONNECTED
    bridge.fail("transport error"); assert bridge.state is ConnectionState.FAILED


def test_received_bytes_are_validated_hashed_and_converted(tmp_path):
    bridge = DeviceBridge(); bridge.connect()
    captured = accepted_image(bridge)
    frame = bridge.to_sampled_frame(captured, tmp_path)
    expected = hashlib.sha256(captured.image_bytes).hexdigest()
    assert hashlib.sha256(frame.image_path.read_bytes()).hexdigest() == expected
    ocr = RapidOcrProvider(engine=lambda image: ([], None)).recognize(frame.image_path, frame.frame_id)
    assert ocr.image_sha256 == expected


def test_duplicate_image_is_dropped_before_second_capture():
    bridge = DeviceBridge(); bridge.connect(); accepted_image(bridge)
    with pytest.raises(DuplicateDeviceMessageError):
        bridge.accept_image_packet(**raw_packet())
    assert [event.event for event in bridge.audit].count("IMAGE_ACCEPTED") == 1


def test_duplicate_voice_command_is_dropped():
    bridge = DeviceBridge(); bridge.connect(); bridge.accept_voice_packet(voice())
    with pytest.raises(DuplicateDeviceMessageError): bridge.accept_voice_packet(voice())
    assert [event.event for event in bridge.audit].count("VOICE_ACCEPTED") == 1


def test_out_of_order_packet_is_rejected():
    bridge = DeviceBridge(); bridge.connect(); accepted_image(bridge, sequence_number=4)
    with pytest.raises(DeviceSequenceError):
        bridge.accept_image_packet(**raw_packet(message_id="new-id", sequence_number=3))


def test_stale_image_and_voice_are_rejected():
    bridge = DeviceBridge(max_packet_age=timedelta(seconds=1)); bridge.connect()
    stale = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(StaleDeviceMessageError):
        bridge.accept_image_packet(**raw_packet(received_at=stale, device_timestamp=stale))
    with pytest.raises(StaleDeviceMessageError): bridge.accept_voice_packet(voice(received=stale))


def test_invalid_device_timestamp_is_recovered_with_audit_field():
    received = NOW
    captured = accepted_image(device_timestamp=NOW - timedelta(days=30), received_at=received)
    assert captured.canonical_capture_timestamp == received
    assert captured.timestamp_source is TimestampSource.RECOVERED


def test_missing_device_timestamp_uses_receiver_explicitly():
    captured = accepted_image(device_timestamp=None)
    assert captured.timestamp_source is TimestampSource.RECEIVER


@pytest.mark.parametrize(
    "content,mime",
    [(b"broken", "image/png"), (POSTER.read_bytes(), "image/gif")],
    ids=["corrupt-bytes", "unsupported-mime"],
)
def test_corrupt_or_unsupported_image_is_rejected(content, mime):
    bridge = DeviceBridge(); bridge.connect()
    with pytest.raises(InvalidDevicePayloadError):
        bridge.accept_image_packet(**raw_packet(image_bytes=content, mime_type=mime))


def test_camera_disconnect_during_capture_and_hud_failure_are_explicit():
    image = accepted_image()
    fake = FakeDeviceAdapter(images=[image]); fake.connect(); fake.disconnect()
    with pytest.raises(DeviceUnavailableError): fake.capture()
    fake.connect(); fake.fail_hud = True
    with pytest.raises(DeviceUnavailableError):
        fake.display(HUDMessage(message_id="h1", created_at=NOW, message_type=HudMessageType.ERROR, title="x", body="y"))


def test_hud_delivery_is_not_user_confirmation():
    hud = BrowserHUDAdapter(); hud.connect()
    message = HUDMessage(
        message_id="hud-confirm", created_at=NOW,
        message_type=HudMessageType.CONFIRMATION_REQUIRED,
        title="确认日程", body="请核对", requires_response=True,
        correlation_id="tx-1",
    )
    hud.display(message)
    assert hud.current == message
    assert not hasattr(hud, "confirm")


def test_local_file_text_and_browser_fallbacks_are_runnable():
    camera = LocalFileCameraAdapter(POSTER); camera.connect()
    captured = camera.capture()
    command = voice()
    text = LocalTextVoiceAdapter([command]); text.connect()
    hud = BrowserHUDAdapter(); hud.connect(); hud.clear()
    fallback = DeviceFallback(
        from_adapter="RokidHUD", to_adapter="BrowserHUD",
        reason="SDK_UNAVAILABLE", occurred_at=NOW,
    )
    assert captured.source_type is DeviceSourceType.FILE_UPLOAD
    assert text.next_command() == command
    assert fallback.event == "DEVICE_FALLBACK"


def test_capability_discovery_supports_partial_devices():
    fake = FakeDeviceAdapter(capabilities=DeviceCapabilities(camera=True, hud=False, microphone=False))
    assert fake.get_capabilities().camera is True
    assert fake.get_capabilities().hud is False


def test_rokid_sdk_absence_never_breaks_import_or_reports_success():
    adapter = RokidSDKUnavailableAdapter()
    assert adapter.healthcheck() is False
    assert adapter.get_capabilities() == DeviceCapabilities()
    with pytest.raises(DeviceUnavailableError, match="SDK_UNAVAILABLE"): adapter.connect()


def test_vision_adapters_are_optional_and_rapidocr_compatible():
    rapid = RapidOCRAdapter(RapidOcrProvider(engine=lambda image: ([], None)))
    assert rapid.recognize(POSTER, "frame-device").success is True
    paddle = PaddleOCRAdapter()
    if not paddle.healthcheck():
        result = paddle.recognize(POSTER, "frame-paddle")
        assert result.success is False and result.provider_version == "SDK_UNAVAILABLE"


def test_fake_glasses_capture_reaches_existing_ocr_and_safety_pipeline(tmp_path):
    bridge = DeviceBridge(); bridge.connect()
    captured = accepted_image(bridge)
    fake = FakeDeviceAdapter(images=[captured], commands=[voice()]); fake.connect()
    device_image = fake.capture()
    frame = bridge.to_sampled_frame(device_image, tmp_path)
    result = process_image(frame.image_path, device_image.canonical_capture_timestamp)
    assert fake.next_command().text == "安排一下"
    assert result.ocr_result is not None and result.ocr_result.image_sha256 == hashlib.sha256(device_image.image_bytes).hexdigest()
    assert result.extraction_result is not None


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("08_low_resolution.png", SafetyGateStatus.RECAPTURE_REQUIRED),
        ("03_weekday_contradiction.png", SafetyGateStatus.CONTRADICTION_BLOCKED),
    ],
)
def test_device_capture_preserves_recapture_and_block_decisions(filename, expected, tmp_path):
    bridge = DeviceBridge(); bridge.connect()
    packet = raw_packet(
        capture_id=f"capture-{filename}", message_id=f"message-{filename}",
        image_bytes=(ROOT / "data" / "synthetic_posters" / filename).read_bytes(),
    )
    captured = bridge.accept_image_packet(**packet)
    frame = bridge.to_sampled_frame(captured, tmp_path)
    result = process_image(frame.image_path, captured.canonical_capture_timestamp)
    assert result.final_status is expected
    assert result.can_proceed_to_confirmation is False


def test_hud_duplicate_does_not_create_any_side_effect():
    fake = FakeDeviceAdapter(); fake.connect()
    bridge = DeviceBridge(); bridge.connect()
    message = HUDMessage(message_id="hud-1", created_at=NOW, message_type=HudMessageType.SUCCESS, title="已创建", body="完成")
    assert bridge.display_hud_once(fake, message) is True
    assert bridge.display_hud_once(fake, message) is False
    assert len(fake.messages) == 1
    assert not hasattr(fake, "calendar")


def test_fake_glasses_full_flow_requires_explicit_confirmation(confirmation_factory, tmp_path):
    bridge = DeviceBridge(); bridge.connect()
    packet = raw_packet(
        capture_id="capture-e2e", message_id="image-e2e",
        image_bytes=POSTER_WITH_DEADLINE.read_bytes(), sequence_number=1,
    )
    captured = bridge.accept_image_packet(**packet)
    fake = FakeDeviceAdapter(images=[captured], commands=[voice(message="voice-e2e")]); fake.connect()
    frame = bridge.to_sampled_frame(fake.capture(), tmp_path)
    pipeline = process_image(frame.image_path, captured.canonical_capture_timestamp)
    assert pipeline.can_proceed_to_confirmation is True
    assert pipeline.extraction_result is not None and pipeline.extraction_result.draft is not None
    assert pipeline.safety_decision is not None

    calendar = MemoryCalendarProvider()
    service = TrustedSchedulingService(calendar)
    preflight = service.preflight(
        pipeline.extraction_result.draft, pipeline.safety_decision, transaction_id="GF-TX-DEVICE-E2E"
    )
    record = service.get_transaction(preflight.transaction_id)
    confirm_hud = HUDMessage(
        message_id="hud-e2e-confirm", created_at=NOW,
        message_type=HudMessageType.CONFIRMATION_REQUIRED,
        title="确认日程", body="等待用户明确确认", requires_response=True,
        correlation_id=preflight.transaction_id,
    )
    fake.display(confirm_hud)
    assert calendar.event_count == 0

    service.confirm(preflight.transaction_id, confirmation_factory(record))
    executed = service.execute(preflight.transaction_id)
    fake.display(HUDMessage(
        message_id="hud-e2e-success", created_at=NOW,
        message_type=HudMessageType.SUCCESS, title="创建成功", body="已回读验证",
        correlation_id=preflight.transaction_id,
    ))
    assert executed.status.value == "VERIFIED"
    assert calendar.event_count == 2
    assert fake.messages[-1].message_type is HudMessageType.SUCCESS
