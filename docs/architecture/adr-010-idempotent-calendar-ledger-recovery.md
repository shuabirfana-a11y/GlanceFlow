# ADR-010: Persistent idempotency ledger and calendar recovery

- Status: Accepted
- Date: 2026-08-06
- Scope: Stage 9 PR3

## Context

ADR-009 prevents an `EXECUTION_UNKNOWN` workflow from issuing another create, but a process can still stop between submitting a provider request and recording its result. Provider timeouts, HTTP failures, delayed indexing, and lost delete responses therefore require durable, provider-neutral recovery evidence.

Treating every timeout as failure can leave an undisclosed event. Retrying blindly can create a duplicate. Treating an unfinished rollback as success can hide a residual side effect.

## Decision

Every planned calendar event receives a client-generated stable `event_id`. Before a create call, the transaction manager persists a minimal ledger entry binding:

- operation and transaction identifiers;
- idempotency key;
- hash of the target calendar;
- hash of the exact event snapshot;
- stable event identifier;
- recovery state, attempt count, timestamps, and a non-sensitive error class.

The ledger never stores notice text, OCR evidence, credentials, OAuth data, access tokens, or the raw calendar identifier. File replacement is atomic on the local filesystem.

On a transient or unknown create result, the manager queries the exact bound `event_id` before any retry. A matching snapshot proceeds to normal readback verification. Confirmed absence permits a bounded retry with the same bindings. An uncertain query, exhausted retry budget, calendar mismatch, snapshot mismatch, or event-ID collision fails closed into recovery or manual recovery.

HTTP 401 and 403 are explicit authorization or permission failures. HTTP 429 and 5xx responses are transient uncertainty. HTTP 409 triggers an exact event-ID query: matching content may recover a prior write, while mismatched content is never overwritten or automatically deleted.

Rollback and undo are complete only after absence is verified for every bound event ID. A restart may reconcile an existing matching create as verified, or a missing rollback target as rollback-verified. It must never convert an existing event from an incomplete rollback into business success.

## Recovery boundary

Startup recovery is read-only. It scans incomplete local entries and reconciles them through exact event-ID reads. It does not restore an old confirmation, repeat a create automatically, delete an event automatically, or use title/time similarity searches.

Entries bound to another calendar, entries with mismatched snapshots, and results that remain uncertain are marked `MANUAL_RECOVERY_REQUIRED`. That state is not reported as success.

## Consequences

- A lost create response cannot cause a blind duplicate retry.
- Provider adapters share explicit error categories and stable event-ID semantics.
- Incomplete rollback and undo remain visible until absence is verified.
- Recovery metadata is durable while privacy-sensitive notice content remains outside the ledger.
- Real Google Calendar calls remain prohibited unless the project owner separately authorizes a dedicated non-primary test calendar and local untracked credentials.
