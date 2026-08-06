import json

import pytest

from glanceflow.application.scheduling_service import TrustedSchedulingService
from glanceflow.calendar.ledger import LedgerState, LocalTransactionLedger
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import TransactionStatus
from glanceflow.calendar.transaction import TransactionStateError
from glanceflow.safety.gate import evaluate_notice


def prepared_service(tmp_path, draft_factory, confirmation_factory, *, faults=None, tx_id="GF-TX-LEDGER"):
    provider = MemoryCalendarProvider(faults)
    ledger_path = tmp_path / "calendar-ledger.json"
    service = TrustedSchedulingService(provider, ledger_path=ledger_path)
    draft = draft_factory()
    service.preflight(draft, evaluate_notice(draft), transaction_id=tx_id)
    record = service.get_transaction(tx_id)
    service.confirm(tx_id, confirmation_factory(record))
    return service, provider, ledger_path


def test_timeout_after_server_success_queries_exact_event_without_duplicate(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, ledger_path = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(timeout_after_create_on_calls={1}),
    )
    result = service.execute("GF-TX-LEDGER")
    assert result.status is TransactionStatus.VERIFIED
    assert provider.event_count == 1
    assert result.created_event_ids == [result.planned_requests[0].event_id]
    assert "CREATE_RESULT_UNKNOWN" in {event.action for event in result.audit_events}
    entries = LocalTransactionLedger(ledger_path).for_transaction("GF-TX-LEDGER")
    assert len(entries) == 1
    assert entries[0].state is LedgerState.VERIFIED_SUCCESS
    assert entries[0].attempt_count == 1


def test_ten_identical_timeouts_never_create_more_than_one_event(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, _ = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(timeout_before_create_on_calls=set(range(1, 11))),
    )
    result = service.execute("GF-TX-LEDGER")
    assert result.status is TransactionStatus.MANUAL_RECOVERY_REQUIRED
    assert provider.event_count <= 1
    assert provider._create_calls == 10


def test_execution_unknown_cannot_call_create_directly(tmp_path, draft_factory, confirmation_factory):
    service, provider, _ = prepared_service(tmp_path, draft_factory, confirmation_factory)
    service._records["GF-TX-LEDGER"].status = TransactionStatus.EXECUTION_UNKNOWN
    with pytest.raises(TransactionStateError, match="禁止直接重复创建"):
        service.execute("GF-TX-LEDGER")
    assert provider._create_calls == 0


def test_query_failure_enters_manual_recovery_and_restart_reconciles_existing_event(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, ledger_path = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(
            timeout_after_create_on_calls={1},
            get_http_status_on_calls={1: 503},
        ),
    )
    uncertain = service.execute("GF-TX-LEDGER")
    assert uncertain.status is TransactionStatus.MANUAL_RECOVERY_REQUIRED
    assert provider.event_count == 1

    provider.fault_plan.get_http_status_on_calls.clear()
    restarted = TrustedSchedulingService(provider, ledger_path=ledger_path)
    reconciled = restarted.recover_incomplete_operations()
    assert [entry.state for entry in reconciled] == [LedgerState.VERIFIED_SUCCESS]
    assert provider.event_count == 1


def test_unknown_existing_mismatch_is_rolled_back_by_bound_event_id(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, _ = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(
            timeout_after_create_on_calls={1},
            tamper_readback_by_role={"MAIN_EVENT": {"title": "mismatch"}},
        ),
    )
    result = service.execute("GF-TX-LEDGER")
    assert result.status is TransactionStatus.ROLLED_BACK
    assert provider.event_count == 0
    assert result.rollback_results[0].event_id == result.planned_requests[0].event_id
    assert result.rollback_results[0].calendar_id == provider.calendar_id


def test_event_id_collision_never_deletes_unrelated_existing_event(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, _ = prepared_service(tmp_path, draft_factory, confirmation_factory)
    record = service.get_transaction("GF-TX-LEDGER")
    planned = record.planned_requests[0]
    unrelated = planned.model_copy(update={"title": "pre-existing unrelated event"})
    provider.create_event(unrelated, "external-key")

    result = service.execute("GF-TX-LEDGER")
    assert result.status is TransactionStatus.MANUAL_RECOVERY_REQUIRED
    assert provider.event_count == 1
    assert provider.get_event(planned.event_id).title == "pre-existing unrelated event"
    assert result.rollback_results == []


def test_delete_response_loss_requires_and_accepts_absence_verification(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, _ = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(
            fail_create_on_calls={2},
            timeout_after_delete_on_calls={1},
        ),
    )
    draft = draft_factory(with_deadline=True)
    service = TrustedSchedulingService(provider, ledger_path=tmp_path / "rollback-ledger.json")
    service.preflight(draft, evaluate_notice(draft), transaction_id="GF-TX-ROLLBACK-LOSS")
    record = service.get_transaction("GF-TX-ROLLBACK-LOSS")
    service.confirm("GF-TX-ROLLBACK-LOSS", confirmation_factory(record))
    result = service.execute("GF-TX-ROLLBACK-LOSS")
    assert result.status is TransactionStatus.ROLLED_BACK
    assert result.rollback_results[0].delete_succeeded is False
    assert result.rollback_results[0].absence_verified is True
    assert provider.event_count == 0


def test_rollback_not_verified_is_never_marked_complete(
    tmp_path, draft_factory, confirmation_factory
):
    provider = MemoryCalendarProvider(
        MemoryFaultPlan(fail_create_on_calls={2}, retain_after_delete_on_calls={1})
    )
    draft = draft_factory(with_deadline=True)
    service = TrustedSchedulingService(provider, ledger_path=tmp_path / "retained-ledger.json")
    service.preflight(draft, evaluate_notice(draft), transaction_id="GF-TX-RETAINED")
    record = service.get_transaction("GF-TX-RETAINED")
    service.confirm("GF-TX-RETAINED", confirmation_factory(record))
    result = service.execute("GF-TX-RETAINED")
    assert result.status is TransactionStatus.FAILED
    assert result.rollback_results[0].absence_verified is False
    assert service.ledger.for_transaction("GF-TX-RETAINED")[0].state is LedgerState.MANUAL_RECOVERY_REQUIRED


def test_restart_never_turns_incomplete_rollback_into_business_success(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, ledger_path = prepared_service(
        tmp_path, draft_factory, confirmation_factory
    )
    result = service.execute("GF-TX-LEDGER")
    entry = service.ledger.for_transaction("GF-TX-LEDGER")[0]
    service.ledger.update(entry.operation_id, LedgerState.ROLLBACK_PENDING)

    restarted = TrustedSchedulingService(provider, ledger_path=ledger_path)
    reconciled = restarted.recover_incomplete_operations()
    assert [item.state for item in reconciled] == [LedgerState.MANUAL_RECOVERY_REQUIRED]
    assert provider.get_event(result.created_event_ids[0]).event_id == result.created_event_ids[0]


def test_restart_can_verify_absence_after_unverified_rollback(
    tmp_path, draft_factory, confirmation_factory
):
    service, provider, ledger_path = prepared_service(
        tmp_path, draft_factory, confirmation_factory
    )
    result = service.execute("GF-TX-LEDGER")
    entry = service.ledger.for_transaction("GF-TX-LEDGER")[0]
    service.ledger.update(
        entry.operation_id,
        LedgerState.MANUAL_RECOVERY_REQUIRED,
        last_error="ROLLBACK_NOT_VERIFIED",
    )
    provider.delete_event(result.created_event_ids[0])

    restarted = TrustedSchedulingService(provider, ledger_path=ledger_path)
    reconciled = restarted.recover_incomplete_operations()
    assert [item.state for item in reconciled] == [LedgerState.ROLLBACK_VERIFIED]


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_explicit_http_rejections_do_not_create(status, tmp_path, draft_factory, confirmation_factory):
    service, provider, _ = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(create_http_status_on_calls={1: status}),
        tx_id=f"GF-TX-HTTP-{status}",
    )
    result = service.execute(f"GF-TX-HTTP-{status}")
    assert result.status is TransactionStatus.FAILED
    assert provider.event_count == 0


@pytest.mark.parametrize("status", [429, 500, 503])
def test_retryable_http_failures_query_before_safe_retry(
    status, tmp_path, draft_factory, confirmation_factory
):
    service, provider, _ = prepared_service(
        tmp_path,
        draft_factory,
        confirmation_factory,
        faults=MemoryFaultPlan(create_http_status_on_calls={1: status}),
        tx_id=f"GF-TX-HTTP-{status}",
    )
    result = service.execute(f"GF-TX-HTTP-{status}")
    assert result.status is TransactionStatus.VERIFIED
    assert provider.event_count == 1
    assert "UNKNOWN_EVENT_ABSENT" in {event.action for event in result.audit_events}


def test_ledger_is_minimal_and_contains_no_notice_or_credentials(
    tmp_path, draft_factory, confirmation_factory
):
    service, _, ledger_path = prepared_service(tmp_path, draft_factory, confirmation_factory)
    service.execute("GF-TX-LEDGER")
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload, ensure_ascii=False).casefold()
    assert "oauth" not in serialized
    assert "token" not in serialized
    assert "ocr" not in serialized
    assert "title" not in serialized
    assert set(payload["entries"][0]) == {
        "schema_version", "operation_id", "transaction_id", "idempotency_key",
        "snapshot_hash", "calendar_id_hash", "event_id", "state", "attempt_count",
        "last_error", "created_at", "last_checked_at",
    }
