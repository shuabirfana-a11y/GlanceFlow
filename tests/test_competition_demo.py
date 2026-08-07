from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from glanceflow.demo.controller import CompetitionDemoController
from glanceflow.demo.healthcheck import run_healthcheck
from glanceflow.demo.run import run_all
from glanceflow.simulator.app import create_app


@pytest.fixture(scope="module")
def demo_results():
    controller = CompetitionDemoController()
    values = {}
    for item in controller.list_scenarios():
        controller.load_scenario(item["scenario_id"])
        values[item["scenario_id"]] = controller.run_auto()
    return values


def test_eight_scenarios_are_fixed_and_use_existing_assets():
    rows = CompetitionDemoController().list_scenarios()
    assert [row["scenario_id"] for row in rows] == [f"GF-DEMO-{n:02d}" for n in range(1, 9)]
    assert all(Path(row["image"]).is_file() for row in rows)
    assert all("expected_status" not in row for row in rows)


def test_normal_and_deadline_transactions_are_verified(demo_results):
    assert demo_results["GF-DEMO-01"]["transaction_status"] == "VERIFIED"
    assert demo_results["GF-DEMO-01"]["calendar_event_count"] == 1
    assert demo_results["GF-DEMO-02"]["calendar_event_count"] == 2


def test_recapture_and_contradiction_have_no_side_effect(demo_results):
    assert demo_results["GF-DEMO-03"]["selected_action"] == "RECAPTURE"
    assert demo_results["GF-DEMO-04"]["selected_action"] == "BLOCK"
    assert demo_results["GF-DEMO-03"]["calendar_event_count"] == demo_results["GF-DEMO-04"]["calendar_event_count"] == 0


def test_conflict_requires_explicit_second_confirmation(demo_results):
    value = demo_results["GF-DEMO-05"]
    assert value["safety"]["CALENDAR CONFLICT"] == "WARN"
    assert any(step["stage"] == "CONFIRMATION" and step["status"] == "WAIT" for step in value["steps"])


def test_undo_duplicate_and_rollback_are_safe(demo_results):
    assert demo_results["GF-DEMO-06"]["transaction_status"] == "UNDONE"
    assert demo_results["GF-DEMO-06"]["calendar_event_count"] == 0
    assert demo_results["GF-DEMO-07"]["selected_action"] == "BLOCK_DUPLICATE"
    assert demo_results["GF-DEMO-07"]["duplicate_events"] == 0
    assert demo_results["GF-DEMO-08"]["transaction_status"] == "ROLLED_BACK"
    assert demo_results["GF-DEMO-08"]["calendar_event_count"] == 0


def test_public_cards_have_no_chain_of_thought_or_sensitive_paths(demo_results):
    encoded = json.dumps(demo_results, ensure_ascii=False)
    assert "chain_of_thought" not in encoded and "C:\\\\Users\\\\" not in encoded
    assert "token" not in encoded.lower() and "oauth" not in encoded.lower()
    assert all(len(item.get("hash", "")) == 8 for value in demo_results.values() for item in value["evidence"])


def test_step_reset_fault_and_export(tmp_path):
    controller = CompetitionDemoController(); controller.load_scenario("GF-DEMO-01")
    first = controller.run_step(); assert first["mode"] == "STEP" and len(first["visible_steps"]) == 1
    assert controller.reset_scenario()["steps"] == []
    controller.load_scenario("GF-DEMO-08"); assert controller.inject_fault("READBACK_MISMATCH")
    controller.run_auto(); controller.export_trace(tmp_path / "trace.json")
    assert (tmp_path / "trace.json").is_file()


def test_healthcheck_and_api_are_offline(tmp_path):
    health = run_healthcheck(tmp_path / "health.json")
    assert health["FINAL"] == "READY_FOR_COMPETITION_DEMO" and health["network_required"] is False
    client = TestClient(create_app())
    assert len(client.get("/api/demo/scenarios").json()["scenarios"]) == 8


def test_repeatability_uses_real_results_without_reliability_claim(monkeypatch, tmp_path, demo_results):
    controller = CompetitionDemoController()
    monkeypatch.setattr(CompetitionDemoController, "_execute", lambda self, scenario: {k: v for k, v in demo_results[scenario.scenario_id].items() if k not in {"mode", "step_index", "visible_steps", "scenario"}})
    payload = run_all(tmp_path, repeat_count=2)["repeatability"]
    assert payload["label"] == "SIMULATOR REPEATABILITY TEST"
    assert payload["not_a_user_reliability_claim"] is True
    assert all(row["crashes"] == row["wrong_side_effects"] == row["duplicate_events"] == 0 for row in payload["results"])


def test_launcher_and_reset_scripts_are_windows_safe():
    launcher = Path("scripts/run_competition_demo.ps1").read_text(encoding="utf-8")
    reset = Path("scripts/reset_competition_demo.ps1").read_text(encoding="utf-8")
    assert "Start-Process" in launcher and "WindowStyle Hidden" in launcher
    assert "Remove-Item -LiteralPath" in reset and "projectRoot" in reset
