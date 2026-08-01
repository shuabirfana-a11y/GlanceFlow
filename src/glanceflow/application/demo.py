from __future__ import annotations

import json
from datetime import timezone
from pathlib import Path

from glanceflow.application.scheduling_service import SchedulingValidationError, TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import CreateEventRequest, EventRole, UserConfirmation
from glanceflow.pipeline import ImagePipelineResult


def _load_ready_result(stage2_path: Path, filename: str) -> ImagePipelineResult:
    data = json.loads(stage2_path.read_text(encoding="utf-8"))
    item = next(
        (entry for entry in data if Path(entry["source_file"]).name == filename),
        None,
    )
    if item is None:
        raise ValueError(f"Stage 2 结果缺少图片：{filename}")
    result = ImagePipelineResult.model_validate(item["result"])
    if (
        not result.can_proceed_to_confirmation
        or result.extraction_result is None
        or result.extraction_result.draft is None
        or result.safety_decision is None
    ):
        raise ValueError(f"Stage 2 图片不是 READY_TO_CONFIRM：{filename}")
    return result


def _confirmation(service: TrustedSchedulingService, transaction_id: str, *, accepted=False):
    record = service.get_transaction(transaction_id)
    main = next(item for item in record.planned_requests if item.event_role is EventRole.MAIN_EVENT)
    deadline = next(
        (item for item in record.planned_requests if item.event_role is EventRole.DEADLINE_EVENT),
        None,
    )
    return UserConfirmation(
        confirmed=True,
        confirmed_at=record.created_at,
        confirmed_title=main.title,
        confirmed_event_start=main.start_time,
        confirmed_location=main.location,
        confirmed_deadline=deadline.start_time if deadline else None,
        accepted_conflict=accepted,
        confirmation_source="calendar-demo-structured-confirmation",
    )


def _external_course(start_time) -> CreateEventRequest:
    from datetime import timedelta

    return CreateEventRequest(
        title="线性代数",
        start_time=start_time + timedelta(minutes=30),
        end_time=start_time + timedelta(minutes=90),
        timezone="Asia/Shanghai",
        location="教学楼101",
        description="用户已有事件；演示程序不会修改它。",
        private_metadata={
            "notice_package_id": "external-course",
            "transaction_id": "external-course",
            "event_role": "MAIN_EVENT",
        },
        notice_package_id="external-course",
        transaction_id="external-course",
        event_role=EventRole.MAIN_EVENT,
    )


def run_calendar_demo(stage2_results_path: Path) -> dict:
    plain = _load_ready_result(stage2_results_path, "01_valid_event.png")
    deadline = _load_ready_result(stage2_results_path, "02_event_with_deadline.png")

    # Normal two-event transaction, followed by precise undo.
    normal_provider = MemoryCalendarProvider()
    normal_service = TrustedSchedulingService(normal_provider)
    normal_tx = "GF-TX-DEMO-NORMAL"
    normal_preflight = normal_service.preflight(
        deadline.extraction_result.draft,
        deadline.safety_decision,
        transaction_id=normal_tx,
    )
    normal_service.confirm(normal_tx, _confirmation(normal_service, normal_tx))
    verified = normal_service.execute(normal_tx)
    undone = normal_service.undo(normal_tx)

    # Conflict remains waiting because accepted_conflict is deliberately false.
    conflict_provider = MemoryCalendarProvider()
    conflict_provider.create_event(
        _external_course(plain.extraction_result.draft.main_event.event_start),
        "external-course",
    )
    conflict_service = TrustedSchedulingService(conflict_provider)
    conflict_tx = "GF-TX-DEMO-CONFLICT"
    conflict_preflight = conflict_service.preflight(
        plain.extraction_result.draft,
        plain.safety_decision,
        transaction_id=conflict_tx,
    )
    conflict_error = None
    try:
        conflict_service.confirm(
            conflict_tx,
            _confirmation(conflict_service, conflict_tx, accepted=False),
        )
    except SchedulingValidationError as exc:
        conflict_error = str(exc)
    conflict_record = conflict_service.get_transaction(conflict_tx)

    # Second event fails: main event must be compensated.
    create_fail_provider = MemoryCalendarProvider(
        MemoryFaultPlan(fail_create_on_calls={2})
    )
    create_fail_service = TrustedSchedulingService(create_fail_provider)
    create_fail_tx = "GF-TX-DEMO-CREATE-FAIL"
    create_fail_preflight = create_fail_service.preflight(
        deadline.extraction_result.draft,
        deadline.safety_decision,
        transaction_id=create_fail_tx,
    )
    create_fail_service.confirm(
        create_fail_tx, _confirmation(create_fail_service, create_fail_tx)
    )
    create_fail_record = create_fail_service.execute(create_fail_tx)

    # Provider returns a changed title during readback: both events roll back.
    mismatch_provider = MemoryCalendarProvider(
        MemoryFaultPlan(
            tamper_readback_by_role={"MAIN_EVENT": {"title": "供应商回读错误标题"}}
        )
    )
    mismatch_service = TrustedSchedulingService(mismatch_provider)
    mismatch_tx = "GF-TX-DEMO-READBACK-MISMATCH"
    mismatch_preflight = mismatch_service.preflight(
        deadline.extraction_result.draft,
        deadline.safety_decision,
        transaction_id=mismatch_tx,
    )
    mismatch_service.confirm(
        mismatch_tx, _confirmation(mismatch_service, mismatch_tx)
    )
    mismatch_record = mismatch_service.execute(mismatch_tx)

    return {
        "generated_at": verified.updated_at.astimezone(timezone.utc).isoformat(),
        "provider": "memory-calendar",
        "google_calendar": {
            "adapter_implemented": True,
            "contract_tested": True,
            "real_call_verified": False,
            "reason": "未提供专用测试日历凭据，未访问真实 Google Calendar。",
        },
        "scenarios": {
            "normal_verified_then_undone": {
                "preflight": normal_preflight.model_dump(mode="json"),
                "verified_transaction": verified.model_dump(mode="json"),
                "undone_transaction": undone.model_dump(mode="json"),
                "final_event_ids": normal_provider.event_ids,
            },
            "conflict_not_accepted": {
                "preflight": conflict_preflight.model_dump(mode="json"),
                "confirmation_error": conflict_error,
                "transaction": conflict_record.model_dump(mode="json"),
                "final_event_ids": conflict_provider.event_ids,
            },
            "second_create_failed": {
                "preflight": create_fail_preflight.model_dump(mode="json"),
                "transaction": create_fail_record.model_dump(mode="json"),
                "final_event_ids": create_fail_provider.event_ids,
            },
            "readback_mismatch": {
                "preflight": mismatch_preflight.model_dump(mode="json"),
                "transaction": mismatch_record.model_dump(mode="json"),
                "final_event_ids": mismatch_provider.event_ids,
            },
        },
    }

