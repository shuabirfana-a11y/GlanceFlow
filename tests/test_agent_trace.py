from glanceflow.agent.evaluation import AgentScenario, _run_scenario


def test_trace_is_complete_and_has_no_sensitive_payload():
    result = _run_scenario(AgentScenario("TRACE", "trace"))
    assert result["trace_completeness"] == 1.0
    serialized = str(result["trace"]).lower()
    assert "api_key" not in serialized
    assert "access_token" not in serialized
    assert "image_path" not in serialized
    assert "main_event" not in serialized
    assert "evidence_lines" not in serialized
    assert "创新创业竞赛宣讲" not in serialized
    assert result["trace"]["steps"][-1]["tool_call"] == "verify_calendar_transaction"
    assert result["trace"]["steps"][-1]["verification_completed"] is True
