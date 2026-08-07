# VisionClaw source analysis

- Repository: `Intent-Lab/VisionClaw`; reviewed commit `675a0bf2595773d09e4a14c8d8a03dba94945044`.
- License: root `LICENSE` is Meta Wearables Developer Terms, with a third-party `NOTICE`; it is not a general MIT/Apache grant. Status: **REFERENCE_ONLY pending legal review**.
- Stack: Swift/iOS sample using Meta Wearables DAT, LiveKit and AVFoundation; Python LiveKit agent; TypeScript gateway. It targets Meta wearable hardware/phone rather than Rokid.

## Real code paths

`samples/CameraAccess/.../StreamSessionViewModel.swift` owns DAT stream/photo state. `OpenClaw/LiveKitSession.swift` publishes microphone and camera and subscribes to returned agent audio. `LatestFrameGrabber` keeps one most-recent frame and supports a frozen/pinned frame. `agent/main.py` joins the LiveKit room, holds the latest `rtc.VideoFrame`, caps attached images at 1024px, and attaches an image only when a tool call requests `attach_view`. `gateway/src/turn.ts` queues textual context and sends it with the next turn; `notify.ts` provides the asynchronous return path.

## Answers to the capture questions

1. It does not attach every frame to tool requests: `FrameHolder` overwrites one latest frame, `encode_latest_frame` encodes on demand, and `attach_view` gates attachment. The realtime model may still consume the published video stream, so this is a tool-context optimization, not proof of low total video bandwidth.
2. Visual context is latest-frame replacement. Pinning mutes the outgoing track so the chosen frame stays the latest shared reference.
3. Microphone and camera are synchronized at the LiveKit room/session level; there is no evidence-grade per-word/per-frame timestamp join suitable for GlanceFlow.
4. Agent status/audio returns through LiveKit and gateway notifications; the Swift UI exposes listening/thinking/speaking state and haptic/status feedback.
5. Transferable capture ideas: latest-frame holder, explicit pin/freeze semantics, opt-in image attachment, image size cap, voice-only degradation, and separating transport session from action execution.

## Fit and exclusions

The capture/session patterns are design references only. Do not copy its agent, prompts, gateway, Meta SDK integration, or live-model action loop. It has no Rokid CXR, Bluetooth SPP, or Rokid HUD implementation. GlanceFlow also requires evidence hashes and deterministic safety/confirmation boundaries that this code does not provide.
