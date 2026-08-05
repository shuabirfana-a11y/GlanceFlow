from __future__ import annotations

from datetime import datetime, timedelta, timezone

from glanceflow.calendar.models import (
    AuditEvent,
    CalendarTransactionRecord,
    CreateEventRequest,
    EventRole,
    TransactionStatus,
)
from glanceflow.calendar.port import CalendarPort, CalendarTransientError
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
    def __init__(self, provider: CalendarPort, records: dict[str, CalendarTransactionRecord]) -> None:
        self.provider = provider
        self.records = records

    def _record(self, transaction_id: str) -> CalendarTransactionRecord:
        try:
            return self.records[transaction_id]
        except KeyError as exc:
            raise TransactionStateError(f"未知事务：{transaction_id}") from exc

    def execute(self, transaction_id: str) -> CalendarTransactionRecord:
        record = self._record(transaction_id)
        if record.status is TransactionStatus.VERIFIED:
            raise TransactionStateError("已验证事务禁止重复执行。")
        if record.status not in {TransactionStatus.CONFIRMED, TransactionStatus.CREATING}:
            raise TransactionStateError(f"事务状态 {record.status.value} 不允许执行。")
        if record.user_confirmation is None or not record.user_confirmation.confirmed:
            raise TransactionStateError("事务缺少有效用户确认。")

        record.status = TransactionStatus.CREATING
        append_audit(record, "CREATE_STARTED", "开始原子化创建日程包。")
        try:
            for request in record.planned_requests:
                snapshot = self.provider.create_event(
                    request,
                    idempotency_key=f"{record.transaction_id}:{request.event_role.value}",
                )
                if snapshot.event_id not in record.created_event_ids:
                    record.created_event_ids.append(snapshot.event_id)
                append_audit(
                    record,
                    "EVENT_CREATED",
                    "事件创建返回稳定 event_id。",
                    event_id=snapshot.event_id,
                    event_role=request.event_role.value,
                )
        except CalendarTransientError:
            record.status = TransactionStatus.CONFIRMED
            append_audit(record, "CREATE_RETRYABLE", "供应商结果不确定，可使用相同事务幂等重试。")
            raise
        except Exception as exc:
            append_audit(record, "CREATE_FAILED", "事件创建失败，启动补偿回滚。", error_type=type(exc).__name__)
            return self._rollback(record)

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
        except CalendarTransientError:
            record.status = TransactionStatus.CONFIRMED
            append_audit(record, "READBACK_RETRYABLE", "回读结果暂不确定，可幂等重试。")
            raise
        except Exception as exc:
            append_audit(record, "READBACK_FAILED", "回读失败，启动补偿回滚。", error_type=type(exc).__name__)
            return self._rollback(record)

        record.status = TransactionStatus.VERIFIED
        append_audit(record, "TRANSACTION_VERIFIED", "日程包全部创建且回读一致。")
        return record.model_copy(deep=True)

    def _rollback(self, record: CalendarTransactionRecord) -> CalendarTransactionRecord:
        record.status = TransactionStatus.ROLLING_BACK
        append_audit(record, "ROLLBACK_STARTED", "删除本事务已创建的全部事件。")
        record.rollback_results = rollback_events(self.provider, record.created_event_ids, record.calendar_id)
        complete = all(result.delete_succeeded and result.absence_verified for result in record.rollback_results)
        record.status = TransactionStatus.ROLLED_BACK if complete else TransactionStatus.FAILED
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
        append_audit(record, "UNDO_STARTED", "按事务记录中的 event_id 精准撤销。")
        record.undo_results = undo_events(self.provider, record.created_event_ids, record.calendar_id)
        complete = all(result.delete_succeeded and result.absence_verified for result in record.undo_results)
        record.status = TransactionStatus.UNDONE if complete else TransactionStatus.FAILED
        append_audit(
            record,
            "UNDO_COMPLETED" if complete else "UNDO_FAILED",
            "事务关联事件已全部撤销。" if complete else "撤销不完整，保留剩余 event_id。",
            remaining_event_ids=[result.event_id for result in record.undo_results if not result.absence_verified],
        )
        return record.model_copy(deep=True)
