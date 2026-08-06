from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from glanceflow.calendar.models import (
    AuditEvent,
    CalendarTransactionRecord,
    CreateEventRequest,
    EventRole,
    TransactionStatus,
)
from glanceflow.calendar.ledger import (
    LedgerEntry,
    LedgerState,
    LocalTransactionLedger,
    calendar_id_digest,
    recovery_snapshot_digest,
)
from glanceflow.calendar.port import (
    CalendarConflictError,
    CalendarError,
    CalendarEventNotFound,
    CalendarPort,
    CalendarTransientError,
)
from glanceflow.calendar.rollback import rollback_events, undo_events
from glanceflow.calendar.verification import verify_readback
from glanceflow.config import DEFAULT_DEADLINE_EVENT_DURATION_MINUTES, DEFAULT_MAIN_EVENT_DURATION_MINUTES
from glanceflow.domain.models import NoticePackageDraft


class TransactionStateError(RuntimeError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def append_audit(record: CalendarTransactionRecord, action: str, message: str, **details) -> None:
    timestamp = now_utc()
    record.updated_at = timestamp
    record.audit_events.append(
        AuditEvent(occurred_at=timestamp, action=action, message=message, details=details)
    )


def plan_event_requests(draft: NoticePackageDraft, transaction_id: str) -> list[CreateEventRequest]:
    common_metadata = {
        "notice_package_id": draft.notice_package_id,
        "transaction_id": transaction_id,
    }
    main_start = draft.main_event.event_start
    requests = [
        CreateEventRequest(
            title=draft.main_event.title,
            start_time=main_start,
            end_time=main_start + timedelta(minutes=DEFAULT_MAIN_EVENT_DURATION_MINUTES),
            timezone=draft.timezone,
            location=draft.main_event.location or None,
            description=(
                f"由 GlanceFlow 从通知包 {draft.notice_package_id} 创建。"
                f"结束时间采用 {DEFAULT_MAIN_EVENT_DURATION_MINUTES} 分钟工程默认时长，并非海报识别结果。"
            ),
            private_metadata={**common_metadata, "event_role": EventRole.MAIN_EVENT.value},
            notice_package_id=draft.notice_package_id,
            transaction_id=transaction_id,
            event_role=EventRole.MAIN_EVENT,
        )
    ]
    if draft.deadline_action is not None:
        deadline = draft.deadline_action
        requests.append(
            CreateEventRequest(
                title=f"【截止】{deadline.action}",
                start_time=deadline.deadline,
                end_time=deadline.deadline + timedelta(minutes=DEFAULT_DEADLINE_EVENT_DURATION_MINUTES),
                timezone=draft.timezone,
                location=None,
                description=(
                    f"由 GlanceFlow 从通知包 {draft.notice_package_id} 创建。"
                    f"提醒时长采用 {DEFAULT_DEADLINE_EVENT_DURATION_MINUTES} 分钟工程默认值。"
                ),
                private_metadata={**common_metadata, "event_role": EventRole.DEADLINE_EVENT.value},
                notice_package_id=draft.notice_package_id,
                transaction_id=transaction_id,
                event_role=EventRole.DEADLINE_EVENT,
            )
        )
    return requests


class CalendarTransactionManager:
    def __init__(
        self,
        provider: CalendarPort,
        records: dict[str, CalendarTransactionRecord],
        ledger: LocalTransactionLedger | None = None,
    ) -> None:
        self.provider = provider
        self.records = records
        self.ledger = ledger or LocalTransactionLedger()

    def _record(self, transaction_id: str) -> CalendarTransactionRecord:
        try:
            return self.records[transaction_id]
        except KeyError as exc:
            raise TransactionStateError(f"未知事务：{transaction_id}") from exc

    def execute(self, transaction_id: str) -> CalendarTransactionRecord:
        record = self._record(transaction_id)
        if record.status is TransactionStatus.VERIFIED:
            raise TransactionStateError("已验证事务禁止重复执行。")
        if record.status is TransactionStatus.EXECUTION_UNKNOWN:
            raise TransactionStateError("EXECUTION_UNKNOWN 禁止直接重复创建；必须先按 event_id 恢复查询。")
        if record.status not in {TransactionStatus.CONFIRMED, TransactionStatus.CREATING}:
            raise TransactionStateError(f"事务状态 {record.status.value} 不允许执行。")
        if record.user_confirmation is None or not record.user_confirmation.confirmed:
            raise TransactionStateError("事务缺少有效用户确认。")

        record.status = TransactionStatus.CREATING
        append_audit(record, "CREATE_STARTED", "开始原子化创建日程包。")
        for request in record.planned_requests:
            snapshot = self._create_with_recovery(record, request)
            if snapshot is None:
                return record.model_copy(deep=True)
            if snapshot.event_id not in record.created_event_ids:
                record.created_event_ids.append(snapshot.event_id)
            append_audit(
                record,
                "EVENT_CREATED",
                "事件创建返回客户端绑定的稳定 event_id。",
                event_id=snapshot.event_id,
                event_role=request.event_role.value,
            )

        record.status = TransactionStatus.EXECUTED_UNVERIFIED
        append_audit(record, "CREATE_COMPLETED_UNVERIFIED", "创建调用完成，必须回读后才能标记成功。")
        record.status = TransactionStatus.READBACK_VERIFYING
        append_audit(record, "READBACK_STARTED", "开始根据真实 event_id 回读验证。")
        record.readback_snapshots.clear()
        record.verification_results.clear()
        try:
            for request, event_id in zip(record.planned_requests, record.created_event_ids, strict=True):
                snapshot = self.provider.get_event(event_id)
                verification = verify_readback(request, snapshot)
                record.readback_snapshots.append(snapshot)
                record.verification_results.append(verification)
                append_audit(
                    record,
                    "READBACK_VERIFIED" if verification.passed else "READBACK_MISMATCH",
                    verification.message,
                    event_id=event_id,
                    mismatch_fields=verification.mismatch_fields,
                )
            if not all(result.passed for result in record.verification_results):
                return self._rollback(record)
        except CalendarTransientError as exc:
            record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
            self._mark_transaction(record, LedgerState.MANUAL_RECOVERY_REQUIRED, type(exc).__name__)
            append_audit(record, "READBACK_UNKNOWN", "回读结果未知，禁止重复创建并转人工恢复。")
            return record.model_copy(deep=True)
        except Exception as exc:
            append_audit(record, "READBACK_FAILED", "回读失败，启动补偿回滚。", error_type=type(exc).__name__)
            return self._rollback(record)

        record.status = TransactionStatus.VERIFIED
        self._mark_transaction(record, LedgerState.VERIFIED_SUCCESS)
        append_audit(record, "TRANSACTION_VERIFIED", "日程包全部创建且回读一致。")
        return record.model_copy(deep=True)

    def _operation(self, record: CalendarTransactionRecord, request: CreateEventRequest) -> LedgerEntry:
        calendar_hash = calendar_id_digest(record.calendar_id)
        snapshot_hash = recovery_snapshot_digest(request)
        seed = f"{calendar_hash}:{record.transaction_id}:{request.event_id}:{snapshot_hash}"
        operation_id = f"OP-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"
        idempotency_key = f"GF-IDEM-{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"
        return self.ledger.prepare(
            operation_id=operation_id,
            transaction_id=record.transaction_id,
            idempotency_key=idempotency_key,
            snapshot_hash=snapshot_hash,
            calendar_id_hash=calendar_hash,
            event_id=request.event_id,
        )

    def _create_with_recovery(
        self, record: CalendarTransactionRecord, request: CreateEventRequest
    ):
        operation = self._operation(record, request)
        for attempt in range(10):
            self.ledger.update(operation.operation_id, LedgerState.CREATE_PENDING, increment_attempt=True)
            try:
                snapshot = self.provider.create_event(request, operation.idempotency_key)
            except CalendarTransientError as exc:
                record.status = TransactionStatus.EXECUTION_UNKNOWN
                self.ledger.update(
                    operation.operation_id,
                    LedgerState.EXECUTION_UNKNOWN,
                    last_error=type(exc).__name__,
                )
                append_audit(
                    record,
                    "CREATE_RESULT_UNKNOWN",
                    "创建结果未知；先按 calendar_id 与客户端 event_id 查询，禁止直接重建。",
                    event_id=request.event_id,
                    attempt=attempt + 1,
                )
                try:
                    snapshot = self.provider.get_event(request.event_id)
                except CalendarEventNotFound:
                    append_audit(record, "UNKNOWN_EVENT_ABSENT", "精确查询未发现事件，允许使用相同绑定重试。")
                    continue
                except Exception as query_exc:
                    record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
                    self.ledger.update(
                        operation.operation_id,
                        LedgerState.MANUAL_RECOVERY_REQUIRED,
                        last_error=type(query_exc).__name__,
                    )
                    append_audit(record, "UNKNOWN_QUERY_FAILED", "精确查询失败，转人工恢复且不再创建。")
                    return None
                if recovery_snapshot_digest(snapshot) != operation.snapshot_hash:
                    if snapshot.event_id not in record.created_event_ids:
                        record.created_event_ids.append(snapshot.event_id)
                    record.status = TransactionStatus.RECOVERY_REQUIRED
                    self.ledger.update(operation.operation_id, LedgerState.RECOVERY_REQUIRED, last_error="SNAPSHOT_MISMATCH")
                    append_audit(record, "UNKNOWN_EVENT_MISMATCH", "event_id 已存在但内容不一致，启动精确回滚。")
                    self._rollback(record)
                    return None
                append_audit(record, "UNKNOWN_EVENT_RECOVERED", "精确查询发现内容一致的事件，继续回读验证。")
            except CalendarConflictError as exc:
                append_audit(
                    record,
                    "CREATE_EVENT_ID_CONFLICT",
                    "供应商报告 event_id 冲突；先精确查询绑定事件，禁止覆盖或盲目删除。",
                    event_id=request.event_id,
                )
                try:
                    snapshot = self.provider.get_event(request.event_id)
                except CalendarEventNotFound:
                    self.ledger.update(
                        operation.operation_id,
                        LedgerState.EXECUTION_REJECTED,
                        last_error=type(exc).__name__,
                    )
                    append_audit(record, "CREATE_REJECTED", "event_id 冲突但精确查询未发现事件。")
                    if record.created_event_ids:
                        self._rollback(record)
                    else:
                        record.status = TransactionStatus.FAILED
                    return None
                except Exception as query_exc:
                    record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
                    self.ledger.update(
                        operation.operation_id,
                        LedgerState.MANUAL_RECOVERY_REQUIRED,
                        last_error=type(query_exc).__name__,
                    )
                    append_audit(record, "CONFLICT_QUERY_FAILED", "冲突事件查询失败，转人工恢复。")
                    return None
                if recovery_snapshot_digest(snapshot) != operation.snapshot_hash:
                    record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
                    self.ledger.update(
                        operation.operation_id,
                        LedgerState.MANUAL_RECOVERY_REQUIRED,
                        last_error="EVENT_ID_COLLISION",
                    )
                    append_audit(
                        record,
                        "EVENT_ID_COLLISION_BLOCKED",
                        "event_id 已存在但内容不匹配；不覆盖、不删除并转人工恢复。",
                    )
                    return None
                append_audit(record, "CONFLICT_EVENT_RECOVERED", "冲突 event_id 内容一致，继续回读验证。")
            except CalendarError as exc:
                self.ledger.update(operation.operation_id, LedgerState.EXECUTION_REJECTED, last_error=type(exc).__name__)
                append_audit(record, "CREATE_REJECTED", "供应商明确拒绝创建。", error_type=type(exc).__name__)
                if record.created_event_ids:
                    self._rollback(record)
                else:
                    record.status = TransactionStatus.FAILED
                return None
            if snapshot.event_id != request.event_id:
                record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
                self.ledger.update(operation.operation_id, LedgerState.MANUAL_RECOVERY_REQUIRED, last_error="EVENT_ID_MISMATCH")
                append_audit(record, "PROVIDER_EVENT_ID_MISMATCH", "供应商返回未绑定 event_id，禁止自动删除或继续执行。")
                return None
            self.ledger.update(operation.operation_id, LedgerState.EXECUTED_UNVERIFIED)
            return snapshot
        record.status = TransactionStatus.MANUAL_RECOVERY_REQUIRED
        self.ledger.update(operation.operation_id, LedgerState.MANUAL_RECOVERY_REQUIRED, last_error="RETRY_LIMIT")
        append_audit(record, "UNKNOWN_RETRY_LIMIT", "精确查询后仍无法确定结果，转人工恢复。")
        return None

    def _mark_transaction(
        self,
        record: CalendarTransactionRecord,
        state: LedgerState,
        last_error: str | None = None,
        event_ids: set[str] | None = None,
    ) -> None:
        for entry in self.ledger.for_transaction(record.transaction_id):
            if event_ids is not None and entry.event_id not in event_ids:
                continue
            self.ledger.update(entry.operation_id, state, last_error=last_error)

    def _rollback(self, record: CalendarTransactionRecord) -> CalendarTransactionRecord:
        record.status = TransactionStatus.ROLLING_BACK
        self._mark_transaction(record, LedgerState.ROLLBACK_PENDING, event_ids=set(record.created_event_ids))
        append_audit(record, "ROLLBACK_STARTED", "删除本事务已创建的全部事件。")
        record.rollback_results = rollback_events(self.provider, record.created_event_ids, record.calendar_id)
        complete = all(result.absence_verified for result in record.rollback_results)
        record.status = TransactionStatus.ROLLED_BACK if complete else TransactionStatus.FAILED
        result_by_id = {result.event_id: result for result in record.rollback_results}
        for entry in self.ledger.for_transaction(record.transaction_id):
            result = result_by_id.get(entry.event_id)
            if result is not None:
                self.ledger.update(
                    entry.operation_id,
                    LedgerState.ROLLBACK_VERIFIED if result.absence_verified else LedgerState.MANUAL_RECOVERY_REQUIRED,
                    last_error=None if result.absence_verified else "ROLLBACK_NOT_VERIFIED",
                )
        append_audit(
            record,
            "ROLLBACK_COMPLETED" if complete else "ROLLBACK_FAILED",
            "补偿回滚完成。" if complete else "补偿回滚不完整，需要人工检查剩余 event_id。",
            remaining_event_ids=[
                result.event_id for result in record.rollback_results if not result.absence_verified
            ],
        )
        return record.model_copy(deep=True)

    def undo(self, transaction_id: str) -> CalendarTransactionRecord:
        record = self._record(transaction_id)
        if record.status is TransactionStatus.UNDONE:
            append_audit(record, "UNDO_ALREADY_COMPLETED", "事务已经撤销，未执行额外删除。")
            return record.model_copy(deep=True)
        if record.status is not TransactionStatus.VERIFIED:
            raise TransactionStateError(f"仅 VERIFIED 事务可以撤销，当前为 {record.status.value}。")
        record.status = TransactionStatus.UNDOING
        self._mark_transaction(record, LedgerState.ROLLBACK_PENDING, event_ids=set(record.created_event_ids))
        append_audit(record, "UNDO_STARTED", "按事务记录中的 event_id 精准撤销。")
        record.undo_results = undo_events(self.provider, record.created_event_ids, record.calendar_id)
        complete = all(result.absence_verified for result in record.undo_results)
        record.status = TransactionStatus.UNDONE if complete else TransactionStatus.FAILED
        result_by_id = {result.event_id: result for result in record.undo_results}
        for entry in self.ledger.for_transaction(record.transaction_id):
            result = result_by_id.get(entry.event_id)
            if result is not None:
                self.ledger.update(
                    entry.operation_id,
                    LedgerState.ROLLBACK_VERIFIED if result.absence_verified else LedgerState.MANUAL_RECOVERY_REQUIRED,
                    last_error=None if result.absence_verified else "UNDO_NOT_VERIFIED",
                )
        append_audit(
            record,
            "UNDO_COMPLETED" if complete else "UNDO_FAILED",
            "事务关联事件已全部撤销。" if complete else "撤销不完整，保留剩余 event_id。",
            remaining_event_ids=[result.event_id for result in record.undo_results if not result.absence_verified],
        )
        return record.model_copy(deep=True)

    def recover_incomplete_operations(self) -> list[LedgerEntry]:
        """Conservatively reconcile persisted operations after process restart."""
        calendar_hash = calendar_id_digest(getattr(self.provider, "calendar_id", "UNSPECIFIED"))
        reconciled: list[LedgerEntry] = []
        for entry in self.ledger.incomplete():
            delete_recovery = entry.state is LedgerState.ROLLBACK_PENDING or entry.last_error in {
                "ROLLBACK_NOT_VERIFIED",
                "UNDO_NOT_VERIFIED",
            }
            if entry.calendar_id_hash != calendar_hash:
                reconciled.append(self.ledger.update(
                    entry.operation_id, LedgerState.MANUAL_RECOVERY_REQUIRED, last_error="CALENDAR_BINDING_MISMATCH"
                ))
                continue
            try:
                snapshot = self.provider.get_event(entry.event_id)
            except CalendarEventNotFound:
                target = (
                    LedgerState.ROLLBACK_VERIFIED
                    if delete_recovery
                    else LedgerState.MANUAL_RECOVERY_REQUIRED
                )
                reconciled.append(self.ledger.update(entry.operation_id, target, last_error=None if target is LedgerState.ROLLBACK_VERIFIED else "EVENT_ABSENT_AFTER_RESTART"))
            except Exception as exc:
                reconciled.append(self.ledger.update(
                    entry.operation_id, LedgerState.MANUAL_RECOVERY_REQUIRED, last_error=type(exc).__name__
                ))
            else:
                target = (
                    LedgerState.VERIFIED_SUCCESS
                    if not delete_recovery
                    and recovery_snapshot_digest(snapshot) == entry.snapshot_hash
                    else LedgerState.MANUAL_RECOVERY_REQUIRED
                )
                reconciled.append(self.ledger.update(
                    entry.operation_id, target, last_error=None if target is LedgerState.VERIFIED_SUCCESS else "SNAPSHOT_MISMATCH"
                ))
        return reconciled
