from __future__ import annotations

from datetime import timezone
from pathlib import Path
from uuid import uuid4

from glanceflow.calendar.models import (
    CalendarPreflightResult,
    CalendarTransactionRecord,
    EventRole,
    TransactionStatus,
    UserConfirmation,
    calendar_request_digest,
)
from glanceflow.calendar.ledger import LedgerEntry, LocalTransactionLedger
from glanceflow.calendar.port import CalendarError, CalendarPort
from glanceflow.calendar.preflight import check_conflict, check_duplicate
from glanceflow.calendar.transaction import (
    CalendarTransactionManager,
    append_audit,
    now_utc,
    plan_event_requests,
)
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.domain.models import NoticePackageDraft
from glanceflow.safety.results import SafetyGateDecision


class SchedulingValidationError(RuntimeError):
    pass


class TrustedSchedulingService:
    def __init__(
        self,
        provider: CalendarPort,
        *,
        ledger: LocalTransactionLedger | None = None,
        ledger_path: Path | None = None,
    ) -> None:
        if ledger is not None and ledger_path is not None:
            raise ValueError("pass either ledger or ledger_path, not both")
        self.provider = provider
        self._records: dict[str, CalendarTransactionRecord] = {}
        self.ledger = ledger or LocalTransactionLedger(ledger_path)
        self._manager = CalendarTransactionManager(provider, self._records, self.ledger)

    def preflight(
        self,
        draft: NoticePackageDraft,
        safety_decision: SafetyGateDecision,
        *,
        transaction_id: str | None = None,
    ) -> CalendarPreflightResult:
        if (
            safety_decision.status is not SafetyGateStatus.READY_TO_CONFIRM
            or not safety_decision.can_proceed_to_confirmation
        ):
            raise SchedulingValidationError("只有 READY_TO_CONFIRM 草案可以进入日历事务层。")
        try:
            canonical_safety_snapshot = NoticePackageDraft.model_validate(
                safety_decision.draft_snapshot
            ).model_dump(mode="json")
        except ValueError as exc:
            raise SchedulingValidationError(
                "Safety Gate draft snapshot is invalid; revalidation is required before preflight"
            ) from exc
        if canonical_safety_snapshot != draft.model_dump(mode="json"):
            raise SchedulingValidationError(
                "draft changed after Safety Gate; revalidation is required before preflight"
            )
        tx_id = transaction_id or f"GF-TX-{uuid4().hex}"
        if tx_id in self._records:
            raise SchedulingValidationError("transaction_id 已存在，禁止创建第二个事务记录。")
        requests = plan_event_requests(draft, tx_id)
        timestamp = now_utc()
        record = CalendarTransactionRecord(
            transaction_id=tx_id,
            calendar_id=getattr(self.provider, "calendar_id", "UNSPECIFIED"),
            notice_package_id=draft.notice_package_id,
            source_draft_snapshot=draft.model_dump(mode="json"),
            safety_decision_snapshot=safety_decision.model_dump(mode="json"),
            status=TransactionStatus.PLANNED,
            planned_requests=requests,
            created_at=timestamp,
            updated_at=timestamp,
        )
        append_audit(record, "TRANSACTION_PLANNED", "已从验证草案生成不可变执行请求。")
        self._records[tx_id] = record

        try:
            duplicate_results = [check_duplicate(self.provider, request) for request in requests]
            main_request = next(request for request in requests if request.event_role is EventRole.MAIN_EVENT)
            conflict = check_conflict(self.provider, main_request)
        except CalendarError as exc:
            record.status = TransactionStatus.FAILED
            append_audit(
                record,
                "PREFLIGHT_PROVIDER_FAILED",
                "日历供应商预检失败，未进入确认或创建阶段。",
                error_type=type(exc).__name__,
            )
            raise SchedulingValidationError("日历供应商预检失败，未创建任何事件。") from exc
        matching = [event for result in duplicate_results for event in result.matching_events]
        bases = sorted({basis for result in duplicate_results for basis in result.comparison_basis})
        duplicate = duplicate_results[0].model_copy(
            update={
                "is_duplicate": bool(matching),
                "matching_events": matching,
                "comparison_basis": bases,
                "message": "发现疑似重复日程，禁止再次创建。" if matching else "未发现重复日程。",
            }
        )
        passed = not duplicate.is_duplicate
        result = CalendarPreflightResult(
            transaction_id=tx_id,
            calendar_id=getattr(self.provider, "calendar_id", "UNSPECIFIED"),
            passed=passed,
            duplicate_result=duplicate,
            conflict_result=conflict,
            requires_conflict_confirmation=conflict.has_conflict,
            planned_requests=requests,
            messages=[duplicate.message, conflict.message],
        )
        record.preflight_result = result
        if not passed:
            record.status = TransactionStatus.CANCELLED
            append_audit(record, "PREFLIGHT_DUPLICATE_BLOCKED", duplicate.message)
        else:
            record.status = TransactionStatus.PREFLIGHT_PASSED
            append_audit(record, "PREFLIGHT_PASSED", "重复与冲突预检完成。")
            record.status = TransactionStatus.WAITING_CONFIRMATION
            append_audit(record, "WAITING_CONFIRMATION", "等待结构化用户确认。")
        return result.model_copy(deep=True)

    def _confirmation_mismatches(
        self, record: CalendarTransactionRecord, confirmation: UserConfirmation
    ) -> list[str]:
        main = next(request for request in record.planned_requests if request.event_role is EventRole.MAIN_EVENT)
        deadline = next(
            (request for request in record.planned_requests if request.event_role is EventRole.DEADLINE_EVENT),
            None,
        )
        mismatches = []
        if confirmation.confirmed_calendar_id != record.calendar_id:
            mismatches.append("calendar_id")
        if confirmation.confirmed_request_hash != calendar_request_digest(record.planned_requests):
            mismatches.append("request_hash")
        if confirmation.confirmed_title != main.title:
            mismatches.append("title")
        if confirmation.confirmed_event_start.astimezone(timezone.utc) != main.start_time.astimezone(timezone.utc):
            mismatches.append("event_start")
        if (confirmation.confirmed_location or "") != (main.location or ""):
            mismatches.append("location")
        expected_deadline = deadline.start_time.astimezone(timezone.utc) if deadline else None
        actual_deadline = (
            confirmation.confirmed_deadline.astimezone(timezone.utc)
            if confirmation.confirmed_deadline
            else None
        )
        if expected_deadline != actual_deadline:
            mismatches.append("deadline")
        return mismatches

    def confirm(self, transaction_id: str, confirmation: UserConfirmation) -> CalendarTransactionRecord:
        record = self._internal_record(transaction_id)
        if record.status is not TransactionStatus.WAITING_CONFIRMATION:
            raise SchedulingValidationError(f"事务状态 {record.status.value} 不允许确认。")
        record.user_confirmation = confirmation.model_copy(deep=True)
        if not confirmation.confirmed:
            append_audit(record, "CONFIRMATION_REJECTED", "用户没有明确确认，未创建事件。")
            raise SchedulingValidationError("用户未明确确认。")
        mismatches = self._confirmation_mismatches(record, confirmation)
        if mismatches:
            append_audit(record, "CONFIRMATION_MISMATCH", "确认字段与计划请求不一致。", fields=mismatches)
            raise SchedulingValidationError(f"确认字段不一致：{', '.join(mismatches)}")
        if record.preflight_result and record.preflight_result.requires_conflict_confirmation:
            if not confirmation.accepted_conflict:
                append_audit(record, "CONFLICT_NOT_ACCEPTED", "存在冲突但用户未二次明确接受。")
                raise SchedulingValidationError("存在冲突，需要 accepted_conflict=True 的二次确认。")
        record.status = TransactionStatus.CONFIRMED
        append_audit(record, "USER_CONFIRMED", "用户确认内容与计划请求完全一致。")
        return record.model_copy(deep=True)

    def execute(self, transaction_id: str) -> CalendarTransactionRecord:
        record = self._internal_record(transaction_id)
        if record.user_confirmation:
            mismatches = self._confirmation_mismatches(record, record.user_confirmation)
            if mismatches:
                raise SchedulingValidationError(
                    f"确认后计划字段发生变化，原确认已失效：{', '.join(mismatches)}"
                )
        return self._manager.execute(transaction_id)

    def undo(self, transaction_id: str) -> CalendarTransactionRecord:
        return self._manager.undo(transaction_id)

    def recover_incomplete_operations(self) -> list[LedgerEntry]:
        return self._manager.recover_incomplete_operations()

    def get_transaction(self, transaction_id: str) -> CalendarTransactionRecord:
        return self._internal_record(transaction_id).model_copy(deep=True)

    def _internal_record(self, transaction_id: str) -> CalendarTransactionRecord:
        try:
            return self._records[transaction_id]
        except KeyError as exc:
            raise SchedulingValidationError(f"未知事务：{transaction_id}") from exc
