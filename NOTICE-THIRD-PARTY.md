# Third-party notice

Stage 12 contains no copied or modified upstream implementation code.

Runtime dependencies already declared by GlanceFlow retain their own licenses.
The new device boundary and adapters were independently implemented against
GlanceFlow contracts. Stage 11 sources were design references only. In
particular, no code was copied from RokidAIAssistant, VisionClaw, RokidGlassAI,
rokid__visual_agent, AssistBridge, or any repository without a confirmed reuse
license.

Potential future sources, not copied in this change:

| Upstream | Commit reviewed | File/pattern reviewed | License | Target | Status |
|---|---|---|---|---|---|
| RealComputer/GlassKit | `3711479cd5e47a01a1e9e152fe607b7470989bee` | CameraX/Camera2 examples | MIT | future Android camera adapter | design only, no copied code |
| PaddlePaddle/PaddleOCR | `2661c7c0ef5c613e8f93c6e93b2e052399f0f854` | `paddleocr/_pipelines/ocr.py` API | Apache-2.0 | optional PaddleOCR adapter | protocol planning only, no copied code |
