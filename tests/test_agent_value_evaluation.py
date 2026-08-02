import csv
import json
from pathlib import Path

import pytest

from glanceflow.evaluation.agent_value import (
    OUTCOME_CLASSES,
    REPRESENTATIVE_IDS,
    SCENARIOS,
    SYSTEMS,
    run_agent_value_evaluation,
)


@pytest.fixture(scope="module")
def value_run(tmp_path_factory):
    output = tmp_path_factory.mktemp("agent-value")
    return output, run_agent_value_evaluation(output, update_docs=False)


def lookup(payload, system, scenario_id):
    return next(item for item in payload["systems"][system] if item["scenario_id"] == scenario_id)


def test_three_systems_use_exactly_the_same_twenty_scenarios(value_run):
    _, payload = value_run
    expected = [item.scenario_id for item in SCENARIOS]
    assert payload["scenario_ids"] == expected
    assert len(expected) == 20
    for system in SYSTEMS:
        assert [item["scenario_id"] for item in payload["systems"][system]] == expected


def test_three_systems_use_same_initial_calendar(value_run):
    _, payload = value_run
    for scenario_id in payload["scenario_ids"]:
        signatures = {lookup(payload, system, scenario_id)["initial_calendar_signature"] for system in SYSTEMS}
        assert len(signatures) == 1
    assert lookup(payload, "direct_execution", "AG-008")["initial_calendar_signature"] == "seed:matching-notice-event"


def test_direct_baseline_normal_capability_is_not_broken(value_run):
    _, payload = value_run
    normal = lookup(payload, "direct_execution", "AG-001")
    deadline = lookup(payload, "direct_execution", "AG-002")
    assert normal["goal_succeeded"] is True and normal["final_event_count"] == 1
    assert deadline["goal_succeeded"] is True and deadline["final_event_count"] == 2
    assert "create_calendar_transaction" in normal["called_tools"]


def test_metric_numerators_denominators_are_recomputed(value_run):
    _, payload = value_run
    expected = {
        "direct_execution": {"wrong_execution_rate": (11, 20), "successful_goal_completion_rate": (5, 20), "recovery_success_rate": (0, 5)},
        "existing_pipeline": {"wrong_execution_rate": (1, 20), "successful_goal_completion_rate": (6, 20), "recovery_success_rate": (2, 5)},
        "optimized_agent": {"wrong_execution_rate": (0, 20), "successful_goal_completion_rate": (10, 20), "recovery_success_rate": (4, 5)},
    }
    for system, values in expected.items():
        for metric, pair in values.items():
            item = payload["metrics"][system][metric]
            assert (item["numerator"], item["denominator"]) == pair
            assert item["value"] == pair[0] / pair[1]


def test_wrong_execution_is_traceable_to_scenario_and_layer(value_run):
    _, payload = value_run
    cases = [detail for results in payload["systems"].values() for item in results for detail in item["wrong_execution_details"]]
    assert cases
    required = {"scenario_id", "input_risks", "system_type", "called_tool", "confirmation_bypassed", "wrong_calendar_event_created", "duplicate_event_created", "residual_event_left", "recoverable", "error_layer", "cost_category"}
    assert all(required <= set(item) for item in cases)
    assert any(item["scenario_id"] == "AG-008" and item["cost_category"] == "重复创建" for item in cases)


def test_safe_block_is_not_counted_as_wrong_execution(value_run):
    _, payload = value_run
    for system in ("existing_pipeline", "optimized_agent"):
        item = lookup(payload, system, "AG-006")
        assert item["unsafe_action_blocked"] is True
        assert item["wrong_execution"] is False
        assert item["final_event_count"] == 0


def test_incomplete_rollback_is_recovery_pending_not_wrong_execution(value_run):
    _, payload = value_run
    for system in ("existing_pipeline", "optimized_agent"):
        item = lookup(payload, system, "AG-018")
        assert item["outcome_class"] == "RECOVERY_PENDING"
        assert item["wrong_execution"] is False
        assert item["recovery_success"] is False
        assert item["final_state"] == "BLOCKED"
        assert item["residual_event_ids"] == ["main-event"]
    assert lookup(payload, "direct_execution", "AG-018")["outcome_class"] == "WRONG_EXECUTION"


def test_every_result_has_one_unified_outcome_class(value_run):
    _, payload = value_run
    assert all(
        item["outcome_class"] in OUTCOME_CLASSES
        for results in payload["systems"].values()
        for item in results
    )


def test_agent_zero_wrong_execution_does_not_come_from_blocking_normal_goals(value_run):
    _, payload = value_run
    agent_metrics = payload["metrics"]["optimized_agent"]
    assert agent_metrics["wrong_execution_rate"]["numerator"] == 0
    assert agent_metrics["unsafe_tool_call_rate"]["numerator"] == 0
    assert agent_metrics["confirmation_bypass_rate"]["numerator"] == 0
    assert agent_metrics["duplicate_execution_rate"]["numerator"] == 0
    for scenario_id, expected_events in (("AG-001", 1), ("AG-002", 2)):
        item = lookup(payload, "optimized_agent", scenario_id)
        assert item["outcome_class"] == "BUSINESS_COMPLETED"
        assert item["final_state"] == "SUCCESS"
        assert item["final_event_count"] == expected_events


def test_protective_delay_reduces_operational_goal_completion(value_run):
    _, payload = value_run
    item = lookup(payload, "optimized_agent", "AG-009")
    assert item["protective_delay"] is True
    assert item["goal_succeeded"] is False
    assert item["safe_resolution"] is True
    assert item["wrong_execution"] is False


def test_decision_cards_are_public_and_sensitive_free(value_run):
    _, payload = value_run
    cards = payload["decision_cards"]
    assert {item["scenario_id"] for item in cards} == set(REPRESENTATIVE_IDS)
    serialized = json.dumps(cards, ensure_ascii=False).lower()
    for forbidden in ("chain_of_thought", "api_key", "access_token", "refresh_token", "c:\\users\\", "image_path", "main_event", "创新创业竞赛宣讲"):
        assert forbidden not in serialized
    assert all(set(card) == {"scenario_id", "state", "risk_level", "selected_action", "tool", "evidence_line_ids", "policy_rules", "public_reason", "side_effect_allowed"} for card in cards)


def test_figures_and_csv_share_the_same_run_data(value_run):
    output, payload = value_run
    rows = list(csv.DictReader((output / "system_comparison.csv").open(encoding="utf-8-sig")))
    assert len(rows) == 60
    for system in SYSTEMS:
        system_rows = [row for row in rows if row["system_id"] == system]
        wrong = sum(row["wrong_execution"] == "True" for row in system_rows)
        assert wrong == payload["metrics"][system]["wrong_execution_rate"]["numerator"]
    figures = sorted((output / "figures").glob("*.png"))
    assert len(figures) == 6
    assert all(path.read_bytes().startswith(b"\x89PNG") and path.stat().st_size > 10_000 for path in figures)


def test_report_and_qa_only_reference_generated_results():
    payload = json.loads(Path("outputs/agent/value_analysis/system_comparison.json").read_text(encoding="utf-8"))
    report = Path("docs/competition/agent-value-report.md").read_text(encoding="utf-8")
    qa = Path("docs/competition/judge-qa.md").read_text(encoding="utf-8")
    direct = payload["metrics"]["direct_execution"]["wrong_execution_rate"]
    agent = payload["metrics"]["optimized_agent"]
    assert f"{direct['numerator']}/{direct['denominator']}" in report
    assert f"{agent['recovery_success_rate']['numerator']}/{agent['recovery_success_rate']['denominator']}" in report
    assert f"{agent['successful_goal_completion_rate']['numerator']}/20" in qa
    forbidden_claims = ("绝对安全", "完全自主", "100%可靠", "行业领先", "已部署真实眼镜", "已完成真实用户大规模验证")
    assert not any(claim in report or claim in qa for claim in forbidden_claims)
