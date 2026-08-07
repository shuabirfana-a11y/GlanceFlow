# Adapter contract

Camera adapters connect/disconnect, capture a path-free `CapturedImage`, report
health, and expose capabilities. Captures carry IDs, exact bytes, dimensions,
MIME type, device/receiver/canonical timestamps, timestamp source, device type,
and sequence number.

Voice adapters return text-only `VoiceCommand` objects; raw audio is not stored.
HUD adapters display or clear `HUDMessage`. A successful `display` call records
delivery only and never satisfies structured user confirmation.

All timestamps are timezone-aware. Images are PNG/JPEG and decoded before
acceptance. Message IDs are deduplicated in a finite window. New IDs with old
sequence numbers and packets older than the configured age are rejected.

Capabilities are explicit: camera, microphone, HUD, realtime stream, still
capture, voice text and optional maximum dimensions. Consumers must branch on
capability rather than device brand.
