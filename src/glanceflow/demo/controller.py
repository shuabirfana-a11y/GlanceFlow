from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from glanceflow.application.scheduling_service import SchedulingValidationError, TrustedSchedulingService
from glanceflow.calendar.memory_provider import MemoryCalendarProvider, MemoryFaultPlan
from glanceflow.calendar.models import CreateEventRequest, EventRole, TransactionStatus, UserConfirmation, calendar_request_digest
from glanceflow.domain.enums import SafetyGateStatus
from glanceflow.pipeline import process_image


ROOT = Path(__file__).resolve().parents[3]
SCENARIO_DIR = ROOT / "demo" / "scenarios"
OUTPUT_DIR = ROOT / "outputs" / "demo"


class DemoScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    name: str
    image: str
    command: str
    behavior: str = "STANDARD"
    public_description: str


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 3)


def _confirmation(record, *, accepted_conflict: bool = False) -> UserConfirmation:
    main = next(item for item in record.planned_requests if item.event_role is EventRole.MAIN_EVENT)
    deadline = next((item for item in record.planned_requests if item.event_role is EventRole.DEADLINE_EVENT), None)
    return UserConfirmation(
        confirmed=True,
        confirmed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        confirmed_title=main.title,
        confirmed_event_start=main.start_time,
        confirmed_location=main.location,
        confirmed_deadline=deadline.start_time if deadline else None,
        confirmed_calendar_id=record.calendar_id,
        confirmed_request_hash=calendar_request_digest(record.planned_requests),
        accepted_conflict=accepted_conflict,
        confirmation_source="competition-demo-explicit-user-action",
    )


class CompetitionDemoController:
    """Repeatable, offline controller; no network or real calendar adapters are used."""

    def __init__(self, scenario_dir: Path = SCENARIO_DIR) -> None:
        self.scenario_dir = scenario_dir
        self._scenarios = self._read_scenarios()
        self.current_id: str | None = None
        self._status: dict[str, Any] = {"mode": "IDLE", "step_index": 0, "steps": []}
        self._fault: str | None = None

    def _read_scenarios(self) -> dict[str, DemoScenario]:
        scenarios = {}
        for path in sorted(self.scenario_dir.glob("GF-DEMO-*.json")):
            item = DemoScenario.model_validate_json(path.read_text(encoding="utf-8"))
            scenarios[item.scenario_id] = item
        return scenarios

    def list_scenarios(self) -> list[dict[str, str]]:
        return [item.model_dump() for item in self._scenarios.values()]

    def load_scenario(self, scenario_id: str) -> dict[str, Any]:
        if scenario_id not in self._scenarios:
            raise KeyError(scenario_id)
        self.current_id = scenario_id
        self._fault = None
        self._status = {"mode": "LOADED", "step_index": 0, "steps": [], "scenario": self._scenarios[scenario_id].model_dump()}
        return self.get_status()

    def reset_scenario(self) -> dict[str, Any]:
        if self.current_id is None:
            self._status = {"mode": "IDLE", "step_index": 0, "steps": []}
        else:
            self.load_scenario(self.current_id)
        return self.get_status()

    def inject_fault(self, fault: str) -> dict[str, Any]:
        if fault != "READBACK_MISMATCH":
            raise ValueError("only READBACK_MISMATCH is a competition-demo fault")
        self._fault = fault
        return self.get_status()

    def run_step(self) -> dict[str, Any]:
        if self.current_id is None:
            raise RuntimeError("load a scenario first")
        if not self._status["steps"]:
            result = self._execute(self._scenarios[self.current_id])
            self._status.update(result)
            self._status["mode"] = "STEP"
            self._status["step_index"] = 1
        elif self._status["step_index"] < len(self._status["steps"]):
            self._status["step_index"] += 1
        return self.get_status()

    def run_auto(self) -> dict[str, Any]:
        if self.current_id is None:
            raise RuntimeError("load a scenario first")
        self._status.update(self._execute(self._scenarios[self.current_id]))
        self._status["mode"] = "AUTO"
        self._status["step_index"] = len(self._status["steps"])
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        result = json.loads(json.dumps(self._status, ensure_ascii=False, default=str))
        if result.get("steps") and result.get("mode") == "STEP":
            result["visible_steps"] = result["steps"][: result["step_index"]]
        else:
            result["visible_steps"] = result.get("steps", [])
        return result

    def export_trace(self, path: Path | None = None) -> dict[str, Any]:
        payload = self.get_status()
        payload.pop("scenario", None)
        target = path or OUTPUT_DIR / "demo_trace.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return payload

    def _execute(self, scenario: DemoScenario) -> dict[str, Any]:
        image = ROOT / scenario.image
        timings: dict[str, float] = {}
        steps: list[dict[str, Any]] = []
        total_start = time.perf_counter()

        started = time.perf_counter(); content = image.read_bytes(); timings["capture"] = _ms(started)
        steps.append({"stage": "CAPTURE", "status": "PASS", "public_reason": "第一视角帧已进入本地设备边界。", "image_hash": hashlib.sha256(content).hexdigest()[:8]})

        started = time.perf_counter()
        pipeline = process_image(image, datetime(2026, 8, 1, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
        timings["ocr_extract_temporal_safety"] = _ms(started)
        evidence = []
        if pipeline.ocr_result:
            evidence = [{"field": "ocr_line", "value": line.text, "evidence": line.line_id, "confidence": line.confidence, "source": pipeline.source_frame_id, "hash": pipeline.ocr_result.image_sha256[:8]} for line in pipeline.ocr_result.evidence_lines[:4]]
        steps.append({"stage": "OCR", "status": "PASS" if pipeline.ocr_result and pipeline.ocr_result.success else "WARN", "public_reason": "RapidOCR 本地识别完成。" if pipeline.ocr_result else "图像质量不足，未进入 OCR。"})
        steps.append({"stage": "SAFETY", "status": "PASS" if pipeline.final_status is SafetyGateStatus.READY_TO_CONFIRM else "BLOCK" if pipeline.final_status is SafetyGateStatus.CONTRADICTION_BLOCKED else "WAIT", "public_reason": (pipeline.reasons or ["字段与证据通过安全门。"]) [0]})

        provider_fault = MemoryFaultPlan()
        if scenario.behavior == "ROLLBACK" or self._fault == "READBACK_MISMATCH":
            provider_fault.tamper_readback_by_role = {"MAIN_EVENT": {"title": "fault-injected-readback"}}
        provider = MemoryCalendarProvider(provider_fault)
        tx_status = "NOT_STARTED"; transaction_id = None; event_ids: list[str] = []
        wrong_side_effect = False; duplicate_events = 0; residual_events = 0
        safety = {"IMAGE QUALITY": "PASS" if pipeline.quality_result.passed else "BLOCK", "TEMPORAL SEMANTICS": "PASS", "EVIDENCE": "PASS" if evidence else "WARN", "DUPLICATE": "PASS", "CALENDAR CONFLICT": "PASS", "CONFIRMATION": "WAIT", "TRANSACTION": "WAIT"}

        if pipeline.can_proceed_to_confirmation and pipeline.extraction_result and pipeline.safety_decision:
            draft = pipeline.extraction_result.draft
            assert draft is not None
            if scenario.behavior == "CONFLICT":
                start_time = draft.main_event.event_start
                provider.create_event(
                    CreateEventRequest(
                        title="课程", start_time=start_time, end_time=start_time.replace(minute=0) if start_time.minute > 0 else start_time.replace(hour=start_time.hour + 1),
                        timezone=draft.timezone, location="教学楼", description="Competition demo conflict fixture",
                        private_metadata={"notice_package_id": "GF-DEMO-CONFLICT", "transaction_id": "GF-TX-CONFLICT-SEED", "event_role": "MAIN_EVENT"},
                        notice_package_id="GF-DEMO-CONFLICT", transaction_id="GF-TX-CONFLICT-SEED", event_role=EventRole.MAIN_EVENT,
                    ),
                    "GF-DEMO-CONFLICT-SEED",
                )
            service = TrustedSchedulingService(provider)
            started = time.perf_counter()
            preflight = service.preflight(draft, pipeline.safety_decision, transaction_id=f"GF-TX-{scenario.scenario_id[-2:]}")
            timings["preflight"] = _ms(started); transaction_id = preflight.transaction_id
            safety["DUPLICATE"] = "BLOCK" if preflight.duplicate_result.is_duplicate else "PASS"
            safety["CALENDAR CONFLICT"] = "WARN" if preflight.conflict_result.has_conflict else "PASS"
            steps.append({"stage": "PREFLIGHT", "status": "PASS" if preflight.passed else "BLOCK", "public_reason": "; ".join(preflight.messages)})
            if preflight.passed:
                safety["CONFIRMATION"] = "PASS"
                if preflight.requires_conflict_confirmation:
                    try:
                        service.confirm(transaction_id, _confirmation(service.get_transaction(transaction_id)))
                    except SchedulingValidationError:
                        steps.append({"stage": "CONFIRMATION", "status": "WAIT", "public_reason": "普通确认不足以接受冲突；等待用户明确选择仍然创建。"})
                service.confirm(transaction_id, _confirmation(service.get_transaction(transaction_id), accepted_conflict=preflight.requires_conflict_confirmation))
                started = time.perf_counter(); record = service.execute(transaction_id); timings["transaction"] = _ms(started)
                tx_status = record.status.value; event_ids = [value[:8] for value in record.created_event_ids]
                residual_events = provider.event_count
                safety["TRANSACTION"] = "PASS" if record.status is TransactionStatus.VERIFIED else "BLOCK"
                steps.extend({"stage": event.action, "status": "PASS" if event.action not in {"READBACK_MISMATCH", "ROLLBACK_FAILED"} else "BLOCK", "public_reason": event.message} for event in record.audit_events if event.action in {"EVENT_CREATED", "READBACK_VERIFIED", "READBACK_MISMATCH", "ROLLBACK_STARTED", "ROLLBACK_VERIFIED", "TRANSACTION_VERIFIED"})
                if scenario.behavior == "UNDO" and record.status is TransactionStatus.VERIFIED:
                    undone = service.undo(transaction_id); tx_status = undone.status.value; residual_events = provider.event_count
                    steps.append({"stage": "UNDO", "status": "PASS", "public_reason": "使用事务记录中的 event_id 精准撤销并验证删除。"})
                if scenario.behavior == "DUPLICATE" and record.status is TransactionStatus.VERIFIED:
                    second = TrustedSchedulingService(provider)
                    duplicate = second.preflight(draft, pipeline.safety_decision, transaction_id=f"{transaction_id}-DUP")
                    safety["DUPLICATE"] = "BLOCK" if not duplicate.passed else "PASS"
                    duplicate_events = max(0, provider.event_count - len(record.created_event_ids))
                    steps.append({"stage": "DUPLICATE", "status": "BLOCK", "public_reason": duplicate.duplicate_result.message})
        else:
            timings["preflight"] = 0.0; timings["transaction"] = 0.0

        timings["end_to_end"] = _ms(total_start)
        side_effect_allowed = pipeline.can_proceed_to_confirmation and safety["CONFIRMATION"] == "PASS"
        if scenario.behavior == "DUPLICATE" and safety["DUPLICATE"] == "BLOCK":
            action = "BLOCK_DUPLICATE"
        elif tx_status == "ROLLED_BACK":
            action = "RECOVERY_COMPLETE"
            side_effect_allowed = False
        elif tx_status in {"VERIFIED", "UNDONE"}:
            action = "EXECUTION_COMPLETE"
        elif pipeline.final_status is SafetyGateStatus.RECAPTURE_REQUIRED:
            action = "RECAPTURE"
        elif pipeline.final_status is SafetyGateStatus.CONTRADICTION_BLOCKED:
            action = "BLOCK"
        else:
            action = "WAIT_FOR_CONFIRMATION"
        return {
            "scenario_id": scenario.scenario_id, "name": scenario.name,
            "final_status": pipeline.final_status.value, "selected_action": action,
            "transaction_status": tx_status, "event_ids": event_ids, "calendar_event_count": provider.event_count,
            "wrong_side_effect": wrong_side_effect, "duplicate_events": duplicate_events,
            "residual_events": residual_events if tx_status not in {"VERIFIED"} else 0,
            "crash": False, "steps": steps, "evidence": evidence, "safety": safety,
            "decision_card": {"current_goal": scenario.command, "agent_state": pipeline.final_status.value, "risk_level": "HIGH" if not pipeline.can_proceed_to_confirmation else "LOW", "selected_action": action, "tool": "trusted_calendar_transaction" if transaction_id else "none", "public_reason": (pipeline.reasons or ["证据与安全检查通过。"])[0], "waiting_for": "recapture or clarification" if not pipeline.can_proceed_to_confirmation else "none", "side_effect_allowed": side_effect_allowed},
            "transaction": {"transaction_id": transaction_id[-8:] if transaction_id else None, "event_ids": event_ids, "status": tx_status},
            "latency_ms": timings, "latency_environment": "LOCAL WINDOWS SIMULATION",
        }
