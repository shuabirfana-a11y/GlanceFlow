# ADR-014: Production device boundary

- Status: Accepted for Fake/Local adapters; Rokid implementation unavailable
- Date: 2026-08-07

## Decision

GlanceFlow introduces `glanceflow.device` as an untrusted transport boundary.
It owns typed camera, voice and HUD contracts; connection state; bounded
deduplication; sequence/staleness checks; timestamp recovery; byte validation;
and conversion into the existing `SampledFrame` model. It does not parse time,
make Agent decisions, authorize confirmation, or write calendars.

Canonical image evidence starts with the exact received bytes. The bridge
decodes those bytes, then persists them and verifies the persisted SHA-256
before OCR. Device timestamps within ten minutes of receiver time are retained;
missing timestamps use receiver time; implausible values use receiver time with
`RECOVERED`. This correction is exposed, never silent.

Transport deduplication complements rather than replaces Agent session and
Calendar transaction idempotency. HUD delivery never constitutes user
confirmation. Fallbacks emit a public `DEVICE_FALLBACK` record.

## Status

- IMPLEMENTED: protocols, models, bridge, byte/hash boundary, VisionAdapter.
- TESTED_WITH_FAKE: camera, text voice, HUD, fault injection, OCR handoff.
- TESTED_WITH_LOCAL_DEVICE: local file upload, text input, browser HUD only.
- NOT_YET_TESTED_ON_ROKID: all CXR/physical glasses behavior.

The Rokid package deliberately returns `SDK_UNAVAILABLE`; no SDK method names
are invented. TemporalSemantics, Evidence Binding, Safety Gate, Action
Preflight, Agent Core, Calendar Transaction, and Recovery remain SDK-free.
