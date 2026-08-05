from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from glanceflow.agent.registry import AgentToolFailure
from glanceflow.agent.tools import AgentRuntimePorts, ToolOutput
from glanceflow.application.scheduling_service import SchedulingValidationError, TrustedSchedulingService
from glanceflow.calendar.models import EventRole, TransactionStatus, UserConfirmation, calendar_request_digest
from glanceflow.domain.models import NoticePackageDraft
from glanceflow.extraction.extractor import DraftExtractor
from glanceflow.ocr.base import OcrProvider
from glanceflow.ocr.models import OcrResult
from glanceflow.safety.gate import evaluate_notice
from glanceflow.safety.results import SafetyGateDecision
from glanceflow.wearable.models import CaptureRequest, CaptureResult, FrameSelectionResult
from glanceflow.wearable.ports import FrameCapturePort


class ExistingCapabilityAdapter:
    """Thin adapters to Stage 1–4 components; safety and transaction logic stay there."""

    def __init__(
        self,
        *,
        capture_provider: FrameCapturePort,
        frame_selector,
        ocr_provider: OcrProvider,
        extractor: DraftExtractor,
        scheduling_service: TrustedSchedulingService,
    ) -> None:
        self.capture_provider = capture_provider
        self.frame_selector = frame_selector
        self.ocr_provider = ocr_provider
        self.extractor = extractor
        self.scheduling_service = scheduling_service

    def ports(self) -> AgentRuntimePorts:
        return AgentRuntimePorts(**{
            "capture_frames": self.capture_frames,
            "select_best_frame": self.select_best_frame,
            "recognize_text": self.recognize_text,
            "extract_notice_draft": self.extract_notice_draft,
            "evaluate_safety": self.evaluate_safety,
            "run_action_preflight": self.run_action_preflight,
            "create_calendar_transaction": self.create_calendar_transaction,
            "verify_calendar_transaction": self.verify_calendar_transaction,
            "rollback_calendar_transaction": self.rollback_calendar_transaction,
            "undo_last_transaction": self.undo_last_transaction,
        })

    @staticmethod
    def _observation(tool_input) -> dict:
        return tool_input.payload["observation"]

    def capture_frames(self, tool_input) -> ToolOutput:
        request = CaptureRequest.model_validate(tool_input.payload["capture_request"])
        result = self.capture_provider.capture(request)
        return ToolOutput(data=result.model_dump(mode="json"), verified=not result.cancelled)

    def select_best_frame(self, tool_input) -> ToolOutput:
        capture = CaptureResult.model_validate(self._observation(tool_input)["capture_result"])
        result: FrameSelectionResult = self.frame_selector.select(capture)
        self.capture_provider.discard_unselected(capture, result.selected_frame_id)
        return ToolOutput(data={
            **result.model_dump(mode="json"),
            "frame_id": result.selected_frame_id,
            "image_path": str(result.selected_image_path) if result.selected_image_path else None,
        }, verified=not result.requires_recapture)

    def recognize_text(self, tool_input) -> ToolOutput:
        selected = self._observation(tool_input)["selected_frame"]
        result = self.ocr_provider.recognize(Path(selected["image_path"]), selected["frame_id"])
        if not result.success:
            raise AgentToolFailure("OCR_TEMPORARY", "本地 OCR 未成功。", retryable=True)
        return ToolOutput(data=result.model_dump(mode="json"), verified=True)

    def extract_notice_draft(self, tool_input) -> ToolOutput:
        observation = self._observation(tool_input)
        ocr = OcrResult.model_validate(observation["ocr_result"])
        result = self.extractor.extract(ocr, datetime.fromisoformat(observation["timestamp"]))
        data = result.model_dump(mode="json")
        if result.draft:
            data["notice_draft"] = result.draft.model_dump(mode="json")
        data["unresolved_fields"] = list(result.missing_fields)
        return ToolOutput(data=data, verified=result.success)

    def evaluate_safety(self, tool_input) -> ToolOutput:
        draft = NoticePackageDraft.model_validate(self._observation(tool_input)["notice_draft"])
        decision = evaluate_notice(draft)
        return ToolOutput(data=decision.model_dump(mode="json"), verified=True)

    def run_action_preflight(self, tool_input) -> ToolOutput:
        observation = self._observation(tool_input)
        draft = NoticePackageDraft.model_validate(observation["notice_draft"])
        decision = SafetyGateDecision.model_validate(observation["safety_decision"])
        try:
            result = self.scheduling_service.preflight(draft, decision)
        except SchedulingValidationError as exc:
            raise AgentToolFailure("PREFLIGHT_FAILED", "行动预检失败，未创建事件。") from exc
        return ToolOutput(data=result.model_dump(mode="json"), verified=True)

    def create_calendar_transaction(self, tool_input) -> ToolOutput:
        record = self.scheduling_service.get_transaction(tool_input.transaction_id)
        main = next(item for item in record.planned_requests if item.event_role is EventRole.MAIN_EVENT)
        deadline = next((item for item in record.planned_requests if item.event_role is EventRole.DEADLINE_EVENT), None)
        phrase = (self._observation(tool_input).get("user_confirmation") or {}).get("phrase", "")
        confirmation = UserConfirmation(
            confirmed=True,
            confirmed_at=datetime.now(timezone.utc),
            confirmed_title=main.title,
            confirmed_event_start=main.start_time,
            confirmed_location=main.location,
            confirmed_deadline=deadline.start_time if deadline else None,
            confirmed_calendar_id=record.calendar_id,
            confirmed_request_hash=calendar_request_digest(record.planned_requests),
            accepted_conflict=phrase == "仍然创建",
            confirmation_source="agent-structured-confirmation",
        )
        try:
            self.scheduling_service.confirm(record.transaction_id, confirmation)
            result = self.scheduling_service.execute(record.transaction_id)
        except SchedulingValidationError as exc:
            raise AgentToolFailure("TRANSACTION_REJECTED", "事务层拒绝执行。") from exc
        return ToolOutput(data=result.model_dump(mode="json"), verified=False)

    def verify_calendar_transaction(self, tool_input) -> ToolOutput:
        record = self.scheduling_service.get_transaction(tool_input.transaction_id)
        verified = record.status is TransactionStatus.VERIFIED and all(item.passed for item in record.verification_results)
        return ToolOutput(data=record.model_dump(mode="json"), verified=verified)

    def rollback_calendar_transaction(self, tool_input) -> ToolOutput:
        record = self.scheduling_service.get_transaction(tool_input.transaction_id)
        verified = record.status is TransactionStatus.ROLLED_BACK and all(item.absence_verified for item in record.rollback_results)
        return ToolOutput(data=record.model_dump(mode="json"), verified=verified)

    def undo_last_transaction(self, tool_input) -> ToolOutput:
        try:
            record = self.scheduling_service.undo(tool_input.transaction_id)
        except SchedulingValidationError as exc:
            raise AgentToolFailure("UNDO_REJECTED", "事务不可撤销或撤销失败。") from exc
        verified = record.status is TransactionStatus.UNDONE and all(item.absence_verified for item in record.undo_results)
        return ToolOutput(data=record.model_dump(mode="json"), verified=verified)
