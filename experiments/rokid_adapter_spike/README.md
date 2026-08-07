# Rokid adapter spike

This directory is an isolated, device-free boundary experiment. It proves that a
Rokid-shaped camera/voice/HUD/connection interface can be translated to the
existing `SampledFrame` capture contract. It does not contain Rokid SDK code,
does not call a real device, and does not modify production adapters.

`VisionAdapter` is deliberately only a protocol. RapidOCR remains the production
OCR provider; PaddleOCR is a future optional adapter and benchmark candidate.
