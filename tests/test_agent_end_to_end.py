from glanceflow.agent.evaluation import SCENARIOS, AgentScenario, _run_scenario, run_agent_evaluation


def test_twenty_scenarios_execute_and_are_traceable(tmp_path):
    report = run_agent_evaluation(tmp_path)
    assert report["scenario_count"] == 20
    assert len(report["scenarios"]) == 20
    assert {item["scenario_id"] for item in report["scenarios"]} == {item.scenario_id for item in SCENARIOS}
    assert all(item["transaction_id"] for item in report["scenarios"])
    assert all(item["trace_completeness"] == 1.0 for item in report["scenarios"])
    assert report["metrics"]["unsafe_tool_call_rate"]["rate"] == 0
    assert report["metrics"]["confirmation_bypass_rate"]["rate"] == 0
    assert report["metrics"]["duplicate_execution_rate"]["rate"] == 0


def test_timeout_recovers_by_verification_without_duplicate_event():
    result = _run_scenario(AgentScenario("TIMEOUT", "timeout", create_timeout_after_success=True))
    assert result["final_state"] == "SUCCESS"
    assert result["recovery_success"] is True
    assert result["final_event_count"] == 1
    assert result["duplicate_execution_attempts"] == 0
    assert any(step["selected_action"] == "VERIFY_TRANSACTION" and "timeout_requires_idempotency_check" in step["policy_rules_triggered"] for step in result["trace"]["steps"])


def test_partial_success_rolls_back_and_rollback_failure_is_visible():
    recovered = _run_scenario(AgentScenario("PARTIAL", "partial", partial_create=True))
    assert recovered["final_state"] == "FAILED" and recovered["final_event_count"] == 0
    assert recovered["recovery_success"] is True
    failed = _run_scenario(AgentScenario("ROLLBACK", "rollback", partial_create=True, rollback_failure=True))
    assert failed["final_state"] == "BLOCKED" and failed["final_event_count"] == 1
    assert failed["recovery_success"] is False


def test_undo_is_precise_and_verified():
    result = _run_scenario(AgentScenario("UNDO", "undo", undo=True))
    assert result["final_state"] == "UNDONE"
    assert result["final_event_count"] == 0
    assert result["side_effect_calls"] == 2
    assert result["transaction_id"] == "GF-TX-UNDO"
