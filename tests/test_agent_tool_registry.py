from datetime import datetime, timezone

from glanceflow.agent.models import AgentSessionState
from glanceflow.agent.registry import AgentToolRegistry, ToolRegistryError
from glanceflow.agent.tools import AgentRuntimePorts, ConfirmedTransactionInput, ToolOutput
from glanceflow.agent.evaluation import AgentScenario, ScenarioRuntime
from glanceflow.agent.adapters import ExistingCapabilityAdapter
from types import SimpleNamespace


def test_whitelist_contains_only_declared_tools():
    runtime = ScenarioRuntime(AgentScenario("T", "tools"))
    registry = AgentToolRegistry.from_ports(runtime.ports())
    assert len(registry.names()) == 10
    try:
        registry.contract("shell")
    except ToolRegistryError as exc:
        assert "whitelist" in str(exc)
    else:
        raise AssertionError("non-whitelisted tool accepted")


def test_input_and_output_validation_and_state_guard():
    runtime = ScenarioRuntime(AgentScenario("T", "tools"))
    registry = AgentToolRegistry.from_ports(runtime.ports())
    invalid = registry.execute("capture_frames", {"payload": {}}, session_state=AgentSessionState.IDLE, confirmation_valid=False)
    assert invalid.success is False and invalid.error_type == "VALIDATION_ERROR"
    blocked = registry.execute("recognize_text", {"session_id": "s", "payload": {}}, session_state=AgentSessionState.IDLE, confirmation_valid=False)
    assert blocked.success is False and blocked.error_type == "POLICY_BLOCK"


def test_provider_exception_is_sanitized():
    runtime = ScenarioRuntime(AgentScenario("T", "tools"))
    ports = runtime.ports()
    ports.handlers["recognize_text"] = lambda _: (_ for _ in ()).throw(RuntimeError("secret-provider-host"))
    registry = AgentToolRegistry.from_ports(ports)
    result = registry.execute("recognize_text", {"session_id": "s", "payload": {}}, session_state=AgentSessionState.READING, confirmation_valid=False)
    assert result.success is False
    assert "secret-provider-host" not in (result.error_message or "")


def test_existing_capability_adapter_uses_trusted_transaction_layer(scheduling_factory):
    service, calendar, draft, _, _ = scheduling_factory(transaction_id="GF-TX-OLD")
    # Use a fresh service because the adapter itself must create the preflight record.
    from glanceflow.application.scheduling_service import TrustedSchedulingService
    from glanceflow.calendar.memory_provider import MemoryCalendarProvider

    calendar = MemoryCalendarProvider()
    service = TrustedSchedulingService(calendar)
    adapter = ExistingCapabilityAdapter(
        capture_provider=None,
        frame_selector=None,
        ocr_provider=None,
        extractor=None,
        scheduling_service=service,
    )
    safety_input = SimpleNamespace(payload={"observation": {"notice_draft": draft.model_dump(mode="json")}})
    safety = adapter.evaluate_safety(safety_input)
    preflight_input = SimpleNamespace(payload={"observation": {"notice_draft": draft.model_dump(mode="json"), "safety_decision": safety.data}})
    preflight = adapter.run_action_preflight(preflight_input)
    tx_id = preflight.data["transaction_id"]
    transaction_input = ConfirmedTransactionInput(
        session_id="session-adapter-test",
        transaction_id=tx_id,
        calendar_id=calendar.calendar_id,
        confirmation_snapshot_id="GF-CONF-adapter-test",
        confirmation_digest="a" * 64,
        confirmed_at=datetime.now(timezone.utc),
    )
    created = adapter.create_calendar_transaction(transaction_input)
    verified = adapter.verify_calendar_transaction(transaction_input)
    assert created.data["status"] == "VERIFIED"
    assert verified.verified is True
    assert calendar.event_count == 1
