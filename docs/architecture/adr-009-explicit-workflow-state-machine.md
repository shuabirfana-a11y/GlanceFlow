# ADR-009: Explicit workflow state machine and confirmation snapshots

- Status: Accepted
- Date: 2026-08-05
- Scope: Stage 9 PR2

## Context

The Stage 7 agent uses a compact operational state enum. It does not separately represent confirmation expiry, rejected preflight, unknown execution results, unverified writes, or recovery ownership. Its confirmation digest also binds only a subset of the values that ultimately affect a calendar write.

Those omissions make safe migration and invariant testing difficult. In particular, an old or unknown state must never be interpreted as permission to write.

## Decision

GlanceFlow adds a versioned workflow state machine alongside the existing operational pipeline. The workflow machine is the security state used to authorize external actions. Operational states remain temporarily available for adapters and Stage 7 evaluation compatibility.

All legal transitions are enumerated in `glanceflow.agent.workflow`. A transition not present in that table fails closed. Unknown legacy states migrate to `MANUAL_REVIEW_REQUIRED`; restored in-flight writes migrate to `EXECUTION_UNKNOWN`, and restored recovery work migrates to `RECOVERY_REQUIRED`. Legacy confirmation data is never restored as valid authorization.

The confirmation snapshot is schema-versioned and binds the draft revision and hash, evidence hash, risk rule version, target calendar, action type, event timing and location, deadline behavior, reminder/recurrence/attendee/conference policies, nonce, confirmation time, and expiry. Changes to any bound field invalidate the snapshot.

External create, update, undo, or rollback tools require:

1. an explicitly allowed action from policy;
2. a legal workflow state for that action;
3. stationary motion state;
4. a current confirmation snapshot bound to the current draft and execution parameters;
5. an unchanged Safety Gate result.

`EXECUTION_UNKNOWN` never permits a repeated create. It permits only readback, user resolution, or recovery routing. Success requires readback verification. Rollback is bound to the transaction's exact calendar and event identifiers and is not considered complete until absence is verified.

## Compatibility and migration

`agent-session-v1` snapshots are accepted through an explicit migration path. Their operational state is mapped conservatively, their confirmation is discarded, and in-flight or unrecognized sessions require recovery or manual review. New snapshots use `agent-session-v2` and record the workflow state directly.

Old sessions are therefore readable but never inherit external-write authority. Old recovery transactions are routed to `RECOVERY_REQUIRED` or `MANUAL_RECOVERY_REQUIRED`; they are not retried as new creates.

## Consequences

- Illegal transitions become mechanically testable.
- Confirmation invalidation has one canonical payload and hash.
- Existing adapters can migrate incrementally without weakening the Safety Gate.
- Some restored sessions require explicit user or manual resolution instead of automatic continuation.
- Idempotent ledger and provider-specific recovery remain Stage 9 PR3 work.
