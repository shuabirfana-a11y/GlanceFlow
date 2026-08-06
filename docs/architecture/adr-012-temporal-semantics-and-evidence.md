# ADR-012: Temporal semantics and field evidence

- Status: Accepted
- Date: 2026-08-06
- Scope: Stage 10 PR5

## Context

A timestamp extracted from a notice is not executable merely because it parses. The same image may contain an event start, event end, registration or submission deadline, check-in time, publication time, cancellation time, an original time, and a rescheduled time. Relative expressions also depend on capture time and the user's timezone. Treating these values as interchangeable can schedule the wrong event.

The previous draft model retained an executable datetime and a list of OCR line IDs, but did not carry the time role, relative-time reference, normalization status, image hash, bounding box, OCR text, or the extraction and Safety Gate versions that justified the value.

## Decision

Each newly extracted time is represented as a strict `TemporalField` containing:

- value, temporal type, timezone, original source text, confidence, deterministic evidence ID;
- relative reference time and normalization status;
- a `TemporalEvidenceBinding` containing image SHA-256, frame ID, bounding box, OCR text, normalized value, OCR confidence/version, extraction-rule version, and Safety Gate rule version.

The supported temporal roles are `EVENT_START`, `EVENT_END`, `REGISTRATION_DEADLINE`, `SUBMISSION_DEADLINE`, `CHECK_IN_TIME`, `PUBLICATION_TIME`, `CANCELLATION_TIME`, `RESCHEDULED_TIME`, and `UNKNOWN_TEMPORAL_FIELD`.

Relative expressions are resolved only when they have a bounded day expression and an explicit clock time. The reference is the capture timestamp converted to the declared user timezone. Ambiguous expressions remain unresolved. A publication time or event end is never promoted to event start. A rescheduled time supersedes an original time while both evidence records remain. Cancellation blocks execution. Multiple candidates with the same executable role are preserved and marked conflicting rather than guessed.

The Safety Gate verifies that executable event and deadline values have exactly one matching temporal field and complete image/frame evidence. Legacy stored drafts without enhanced fields remain readable; new deterministic extraction emits version `deterministic-v2` and the enhanced fields.

## Consequences

- Calendar planning continues to receive the existing validated draft fields, preserving provider and transaction behavior.
- Evidence mutations that disagree with OCR text, normalized value, confidence, or source frame fail model validation or the Safety Gate.
- Missing image hashes, unresolved time expressions, cancellations, and same-role conflicts cannot become external Calendar writes.
- The change adds no external API calls, persistent personal data, or formal PUBLIC_WEB evaluation.
