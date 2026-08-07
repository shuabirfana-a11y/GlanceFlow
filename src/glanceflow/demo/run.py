from __future__ import annotations

import csv
import json
from pathlib import Path

from glanceflow.demo.controller import CompetitionDemoController, OUTPUT_DIR
from glanceflow.demo.healthcheck import run_healthcheck


CORE = [f"GF-DEMO-{number:02d}" for number in range(1, 7)]


def run_all(output_dir: Path = OUTPUT_DIR, repeat_count: int = 10) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    controller = CompetitionDemoController()
    results = []
    for item in controller.list_scenarios():
        controller.load_scenario(item["scenario_id"])
        results.append(controller.run_auto())
    (output_dir / "scenario_results.json").write_text(json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    repeats = []
    for scenario_id in CORE:
        runs = []
        for iteration in range(1, repeat_count + 1):
            controller.load_scenario(scenario_id)
            value = controller.run_auto()
            runs.append({"iteration": iteration, "selected_action": value["selected_action"], "transaction_status": value["transaction_status"], "wrong_side_effect": value["wrong_side_effect"], "duplicate_events": value["duplicate_events"], "residual_events": value["residual_events"], "crash": value["crash"]})
        repeats.append({"scenario_id": scenario_id, "runs": runs, "successful_runs": sum(not r["crash"] and not r["wrong_side_effect"] for r in runs), "wrong_side_effects": sum(r["wrong_side_effect"] for r in runs), "duplicate_events": sum(r["duplicate_events"] for r in runs), "unclean_transactions": sum(r["residual_events"] for r in runs), "crashes": sum(r["crash"] for r in runs)})
    repeat_payload = {"label": "SIMULATOR REPEATABILITY TEST", "runs_per_scenario": repeat_count, "results": repeats, "not_a_user_reliability_claim": True}
    (output_dir / "repeatability_results.json").write_text(json.dumps(repeat_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output_dir / "latency_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["scenario_id", "capture_ms", "ocr_extract_temporal_safety_ms", "preflight_ms", "transaction_ms", "end_to_end_ms", "environment"]
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for result in results:
            latency = result["latency_ms"]
            writer.writerow({"scenario_id": result["scenario_id"], "capture_ms": latency["capture"], "ocr_extract_temporal_safety_ms": latency["ocr_extract_temporal_safety"], "preflight_ms": latency["preflight"], "transaction_ms": latency["transaction"], "end_to_end_ms": latency["end_to_end"], "environment": result["latency_environment"]})
    run_healthcheck(output_dir / "demo_health.json")
    controller.load_scenario("GF-DEMO-05"); controller.run_auto(); controller.export_trace(output_dir / "demo_trace.json")
    summary = ["# Competition demo summary", "", "- Environment: **LOCAL WINDOWS SIMULATION**", "- Network required: **no**", "- Calendar: **MemoryCalendar only**", "- Rokid hardware validation: **not performed**", "", "## Scenario outcomes", "", "| Scenario | Safety status | Action | Transaction | Calendar events |", "|---|---|---|---|---:|"]
    summary.extend(f"| {r['scenario_id']} | {r['final_status']} | {r['selected_action']} | {r['transaction_status']} | {r['calendar_event_count']} |" for r in results)
    summary.extend(["", "## Repeatability", "", f"Six core simulator scenarios were each run {repeat_count} times. These are deterministic simulator repeatability checks, not real-user or hardware reliability statistics."])
    (output_dir / "demo_summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    return {"scenarios": results, "repeatability": repeat_payload}


def main() -> int:
    result = run_all()
    print(f"SCENARIOS={len(result['scenarios'])}")
    print("REPEATABILITY=6x10")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
