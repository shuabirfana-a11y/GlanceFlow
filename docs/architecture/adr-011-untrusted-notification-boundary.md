# ADR-011: Untrusted notification input boundary

- Status: Accepted
- Date: 2026-08-06
- Scope: Stage 10 PR4

## Context

OCR and notification content are evidence, not instructions. A notice can contain prompt-injection text, tool-call JSON, a forged confirmation, a requested target calendar, attendee or conference instructions, hidden text, or a forged motion state. Passing the complete observation to an external-write adapter unnecessarily mixes that untrusted content with user intent and trusted runtime state.

## Decision

GlanceFlow represents the three authorities with separate strict models:

- `USER_COMMAND` carries an explicit user response accepted by the current workflow state;
- `NOTIFICATION_CONTENT` carries only OCR results and a candidate notice draft;
- `SYSTEM_STATE` carries runtime-owned state such as motion and the centralized session state.

Notification input cannot contain confirmation, allowed-action, calendar-selection, or system-state fields. Extra fields fail validation. Only the policy enumerates allowed actions, and only the user-command entry point can issue a confirmation snapshot.

Before an external Calendar create, a deterministic builder produces `ConfirmedTransactionInput` solely from the policy-controlled session, preflight transaction binding, and valid confirmation snapshot. The command contains the transaction ID, explicit non-primary calendar binding, confirmation identity and digest, confirmation timestamp, and a boolean conflict acceptance. It contains no OCR result, notice draft, free-text instruction, attendee list, conference request, or tool-call payload.

The Calendar adapter loads the already planned immutable requests from `TrustedSchedulingService`. It rejects a calendar-binding mismatch and constructs `UserConfirmation` from the trusted command and stored transaction record. Notification text therefore cannot select the target calendar, expand tool permissions, invite attendees, create a conference entry, or bypass confirmation.

## Consequences

- Prompt-like text remains ordinary notification evidence.
- Replacing OCR evidence after confirmation invalidates the confirmation snapshot.
- Existing deterministic draft extraction, Safety Gate, preflight, idempotency, verification, rollback, and recovery controls remain in force.
- The boundary is provider-neutral and introduces no external side effects or new stored personal data.
- Real Google Calendar operations and formal PUBLIC_WEB evaluation remain outside this change.
