# ADR-013: Rokid device adapter boundary

- Status: Proposed / isolated PoC
- Date: 2026-08-07

## Context

GlanceFlow currently receives local simulator captures. Real Rokid integration introduces proprietary Android SDKs, permissions, Bluetooth/CXR lifecycle, device errors, and HUD constraints. These concerns must not leak into trusted scheduling semantics.

## Decision

```text
Rokid Glasses
  ├─ CameraAdapter
  ├─ VoiceAdapter
  └─ HUDAdapter
         │
  DeviceConnectionAdapter / Device Bridge
         │
  existing Capture and Voice event contracts
         │
  GlanceFlow Core → Existing Agent
```

Define SDK-neutral `CameraAdapter`, `VoiceAdapter`, `HUDAdapter`, `DeviceConnectionAdapter`, and `VisionAdapter` protocols. Android-specific CXR/Camera2/Bluetooth code lives in a separately licensed device package. The bridge converts image bytes to the existing `SampledFrame` boundary and voice into existing structured trigger events. HUD output is display-only and cannot authorize actions.

Messages carry protocol version, stable message ID, type, timestamp, bounded payload length, and acknowledgement status. Reconnect retries transport only; deduplication prevents a retried message from creating a second core input. Disconnect, timeout, invalid image, and HUD failure are explicit states. No device result can bypass evidence validation, Safety Gate, Action Preflight, confirmation, or transaction idempotency.

`VisionAdapter` exposes `recognize`, `healthcheck`, `get_version`, and `get_capabilities`. RapidOCR remains production default. PaddleOCR is optional only after a like-for-like Windows CPU benchmark and must emit the existing OCR evidence schema.

## Invariants

TemporalSemantics, Evidence Binding, Safety Gate, Action Preflight, Agent Core, Calendar Transaction, and Recovery have no Rokid SDK dependency and remain unchanged. Moving/unknown posture still cannot confirm or execute. Raw video/audio is not persistently retained. Device credentials stay local and untracked. Stage 11 makes no claim of real-device validation.

## PoC evidence and next step

`experiments/rokid_adapter_spike` independently demonstrates fake capture, voice, HUD, connection/disconnection, bad-image handling, and conversion to `SampledFrame` without any SDK. Real integration next requires a supported Rokid device, paired Android phone, official developer access/Maven artifacts, application identity/authentication material kept outside Git, Android camera/microphone/Bluetooth permissions, and a non-production test environment.
