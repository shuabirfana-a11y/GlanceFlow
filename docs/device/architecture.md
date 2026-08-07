# Device architecture

`CameraAdapter`, `VoiceAdapter`, and `HUDAdapter` feed a `DeviceBridge`. The
bridge accepts only connected transports, validates packet identity/order/age,
normalizes timestamp provenance, validates image bytes, and converts accepted
images to the existing wearable capture contract.

```text
Device/Fake/Local adapters
  -> DeviceBridge (transport reliability)
  -> SampledFrame / VoiceCommand / HUDMessage
  -> existing OCR, evidence, safety, Agent and transaction layers
```

The bridge has `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DEGRADED`,
`RECONNECTING`, and `FAILED` states. It intentionally has no CalendarPort and no
confirmation method.
