# Open-source reuse matrix

| Capability | Source evidence | Use mode | GlanceFlow target |
|---|---|---|---|
| still-photo capture and orientation fallback | RokidAIAssistant `GlassesCameraManager`, GlassKit `CameraScreenController` | design reference; only GlassKit code is license-eligible | `RokidCameraAdapter` |
| CXR isolation | `rokid__visual_agent` transport modules; RokidAIAssistant CXR managers | design reference only | Android `DeviceBridge` implementations |
| framed phone/glasses photo transfer | RokidAIAssistant `PhotoTransferProtocol` and receiver | design reference only | versioned bridge envelope with message ID/ack |
| HUD relay/outbox | AssistBridge protocol, relay and `AssistantHudView` | design reference only | `RokidHUDAdapter` |
| realtime capture with fallback | GlassKit CameraX/WebRTC examples | reusable with MIT attribution or independent implementation | optional stream-capable `CameraAdapter` |
| latest/pinned visual context | VisionClaw `FrameHolder`/`LatestFrameGrabber` | design reference only | Capture-layer frame selection, never Agent bypass |
| OCR | PaddleOCR `PaddleOCR.predict` pipeline | optional Apache-2.0 adapter after benchmark | `PaddleOCRAdapter` |
| current OCR | GlanceFlow RapidOCR provider | keep | `RapidOCRAdapter` |
| Agent Core | GlanceFlow | KEEP GLANCEFLOW OWN IMPLEMENTATION | unchanged |
| Safety / Action Preflight | GlanceFlow | KEEP GLANCEFLOW OWN IMPLEMENTATION | unchanged |
| temporal semantics/evidence | GlanceFlow | KEEP GLANCEFLOW OWN IMPLEMENTATION | unchanged |
| calendar transaction/recovery | GlanceFlow | KEEP GLANCEFLOW OWN IMPLEMENTATION | unchanged |

The five highest-value modules/patterns are: CXR transport separation, Camera2/CameraX capture fallback, framed photo transfer, HUD relay with explicit outbox state, and latest/pinned-frame capture context. All device messages should be bounded, versioned, authenticated by the official SDK where available, assigned stable IDs, acknowledged, timed out, and deduplicated before entering core capture.
