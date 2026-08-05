from __future__ import annotations

from enum import StrEnum


class WorkflowState(StrEnum):
    DRAFT = "DRAFT"
    NEED_USER_INPUT = "NEED_USER_INPUT"
    RECAPTURE_REQUIRED = "RECAPTURE_REQUIRED"
    CONTRADICTION_BLOCKED = "CONTRADICTION_BLOCKED"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    READY_TO_CONFIRM = "READY_TO_CONFIRM"
    CONFIRMATION_PENDING = "CONFIRMATION_PENDING"
    CONFIRMED = "CONFIRMED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    CONFIRMATION_INVALIDATED = "CONFIRMATION_INVALIDATED"
    PREFLIGHT_PENDING = "PREFLIGHT_PENDING"
    PREFLIGHT_REJECTED = "PREFLIGHT_REJECTED"
    PREFLIGHT_PASSED = "PREFLIGHT_PASSED"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_REJECTED = "EXECUTION_REJECTED"
    EXECUTION_UNKNOWN = "EXECUTION_UNKNOWN"
    EXECUTED_UNVERIFIED = "EXECUTED_UNVERIFIED"
    VERIFIED_SUCCESS = "VERIFIED_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    ROLLBACK_PENDING = "ROLLBACK_PENDING"
    ROLLBACK_VERIFIED = "ROLLBACK_VERIFIED"
    USER_RESOLUTION_REQUIRED = "USER_RESOLUTION_REQUIRED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    MANUAL_RECOVERY_REQUIRED = "MANUAL_RECOVERY_REQUIRED"


class WorkflowStateError(RuntimeError):
    pass


ALLOWED_WORKFLOW_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.DRAFT: frozenset({
        WorkflowState.NEED_USER_INPUT,
        WorkflowState.RECAPTURE_REQUIRED,
        WorkflowState.CONTRADICTION_BLOCKED,
        WorkflowState.OUT_OF_SCOPE,
        WorkflowState.READY_TO_CONFIRM,
        WorkflowState.PREFLIGHT_PENDING,
    }),
    WorkflowState.NEED_USER_INPUT: frozenset({
        WorkflowState.DRAFT,
        WorkflowState.RECAPTURE_REQUIRED,
        WorkflowState.CONTRADICTION_BLOCKED,
        WorkflowState.OUT_OF_SCOPE,
    }),
    WorkflowState.RECAPTURE_REQUIRED: frozenset({WorkflowState.DRAFT, WorkflowState.OUT_OF_SCOPE}),
    WorkflowState.CONTRADICTION_BLOCKED: frozenset({WorkflowState.MANUAL_REVIEW_REQUIRED}),
    WorkflowState.OUT_OF_SCOPE: frozenset(),
    WorkflowState.READY_TO_CONFIRM: frozenset({WorkflowState.CONFIRMATION_PENDING, WorkflowState.DRAFT}),
    WorkflowState.CONFIRMATION_PENDING: frozenset({
        WorkflowState.CONFIRMED,
        WorkflowState.CONFIRMATION_EXPIRED,
        WorkflowState.CONFIRMATION_INVALIDATED,
        WorkflowState.DRAFT,
    }),
    WorkflowState.CONFIRMED: frozenset({
        WorkflowState.CONFIRMATION_EXPIRED,
        WorkflowState.CONFIRMATION_INVALIDATED,
        WorkflowState.PREFLIGHT_PENDING,
        WorkflowState.EXECUTION_PENDING,
    }),
    WorkflowState.CONFIRMATION_EXPIRED: frozenset({WorkflowState.CONFIRMATION_PENDING, WorkflowState.DRAFT}),
    WorkflowState.CONFIRMATION_INVALIDATED: frozenset({WorkflowState.CONFIRMATION_PENDING, WorkflowState.DRAFT}),
    WorkflowState.PREFLIGHT_PENDING: frozenset({
        WorkflowState.PREFLIGHT_REJECTED,
        WorkflowState.PREFLIGHT_PASSED,
        WorkflowState.CONFIRMATION_INVALIDATED,
    }),
    WorkflowState.PREFLIGHT_REJECTED: frozenset({
        WorkflowState.NEED_USER_INPUT,
        WorkflowState.CONFIRMATION_INVALIDATED,
        WorkflowState.USER_RESOLUTION_REQUIRED,
        WorkflowState.MANUAL_REVIEW_REQUIRED,
    }),
    WorkflowState.PREFLIGHT_PASSED: frozenset({
        WorkflowState.READY_TO_CONFIRM,
        WorkflowState.CONFIRMATION_PENDING,
        WorkflowState.EXECUTION_PENDING,
        WorkflowState.CONFIRMATION_INVALIDATED,
    }),
    WorkflowState.EXECUTION_PENDING: frozenset({
        WorkflowState.CONFIRMATION_INVALIDATED,
        WorkflowState.EXECUTION_REJECTED,
        WorkflowState.EXECUTION_UNKNOWN,
        WorkflowState.EXECUTED_UNVERIFIED,
        WorkflowState.RECOVERY_REQUIRED,
    }),
    WorkflowState.EXECUTION_REJECTED: frozenset({WorkflowState.CONFIRMATION_INVALIDATED, WorkflowState.USER_RESOLUTION_REQUIRED}),
    WorkflowState.EXECUTION_UNKNOWN: frozenset({
        WorkflowState.EXECUTED_UNVERIFIED,
        WorkflowState.RECOVERY_REQUIRED,
        WorkflowState.USER_RESOLUTION_REQUIRED,
        WorkflowState.MANUAL_RECOVERY_REQUIRED,
    }),
    WorkflowState.EXECUTED_UNVERIFIED: frozenset({
        WorkflowState.VERIFIED_SUCCESS,
        WorkflowState.ROLLBACK_VERIFIED,
        WorkflowState.VERIFICATION_FAILED,
        WorkflowState.EXECUTION_UNKNOWN,
    }),
    WorkflowState.VERIFIED_SUCCESS: frozenset({WorkflowState.CONFIRMATION_PENDING}),
    WorkflowState.VERIFICATION_FAILED: frozenset({WorkflowState.RECOVERY_REQUIRED, WorkflowState.MANUAL_RECOVERY_REQUIRED}),
    WorkflowState.RECOVERY_REQUIRED: frozenset({
        WorkflowState.ROLLBACK_PENDING,
        WorkflowState.EXECUTED_UNVERIFIED,
        WorkflowState.USER_RESOLUTION_REQUIRED,
        WorkflowState.MANUAL_RECOVERY_REQUIRED,
    }),
    WorkflowState.ROLLBACK_PENDING: frozenset({WorkflowState.ROLLBACK_VERIFIED, WorkflowState.MANUAL_RECOVERY_REQUIRED}),
    WorkflowState.ROLLBACK_VERIFIED: frozenset(),
    WorkflowState.USER_RESOLUTION_REQUIRED: frozenset({
        WorkflowState.CONFIRMATION_PENDING,
        WorkflowState.RECOVERY_REQUIRED,
        WorkflowState.MANUAL_REVIEW_REQUIRED,
    }),
    WorkflowState.MANUAL_REVIEW_REQUIRED: frozenset({
        WorkflowState.DRAFT,
        WorkflowState.OUT_OF_SCOPE,
        WorkflowState.MANUAL_RECOVERY_REQUIRED,
    }),
    WorkflowState.MANUAL_RECOVERY_REQUIRED: frozenset({WorkflowState.RECOVERY_REQUIRED, WorkflowState.ROLLBACK_PENDING}),
}


def transition_workflow(current: WorkflowState, target: WorkflowState) -> WorkflowState:
    if target == current:
        return current
    if target not in ALLOWED_WORKFLOW_TRANSITIONS[current]:
        raise WorkflowStateError(f"illegal workflow state transition: {current.value} -> {target.value}")
    return target


LEGACY_STATE_MIGRATION: dict[str, WorkflowState] = {
    "IDLE": WorkflowState.DRAFT,
    "CAPTURING": WorkflowState.DRAFT,
    "SELECTING_FRAME": WorkflowState.DRAFT,
    "READING": WorkflowState.DRAFT,
    "EXTRACTING": WorkflowState.DRAFT,
    "VALIDATING": WorkflowState.DRAFT,
    "PREFLIGHTING": WorkflowState.PREFLIGHT_PENDING,
    "NEED_INPUT": WorkflowState.NEED_USER_INPUT,
    "RECAPTURE_REQUIRED": WorkflowState.RECAPTURE_REQUIRED,
    "BLOCKED": WorkflowState.MANUAL_REVIEW_REQUIRED,
    "WAIT_CONFIRM": WorkflowState.CONFIRMATION_PENDING,
    "EXECUTING": WorkflowState.EXECUTION_UNKNOWN,
    "VERIFYING": WorkflowState.EXECUTED_UNVERIFIED,
    "RECOVERING": WorkflowState.RECOVERY_REQUIRED,
    "SUCCESS": WorkflowState.VERIFIED_SUCCESS,
    "UNDONE": WorkflowState.ROLLBACK_VERIFIED,
    "CANCELLED": WorkflowState.USER_RESOLUTION_REQUIRED,
    "FAILED": WorkflowState.MANUAL_RECOVERY_REQUIRED,
}


def migrate_legacy_state(value: str | None) -> WorkflowState:
    if value is None:
        return WorkflowState.MANUAL_REVIEW_REQUIRED
    try:
        return WorkflowState(value)
    except ValueError:
        return LEGACY_STATE_MIGRATION.get(value, WorkflowState.MANUAL_REVIEW_REQUIRED)
