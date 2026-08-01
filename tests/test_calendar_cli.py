import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_calendar_demo_cli_generates_all_scenarios(tmp_path):
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "glanceflow.cli",
            "calendar-demo",
            "--stage2-results",
            str(ROOT / "outputs" / "stage2_results.json"),
        ],
        cwd=tmp_path,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "normal_verified_then_undone: UNDONE" in result.stdout
    assert "conflict_not_accepted: WAITING_CONFIRMATION" in result.stdout
    assert "second_create_failed: ROLLED_BACK" in result.stdout
    assert "readback_mismatch: ROLLED_BACK" in result.stdout

    output = tmp_path / "outputs" / "stage3_results.json"
    assert output.is_file()
    data = json.loads(output.read_text(encoding="utf-8"))
    scenarios = data["scenarios"]
    normal = scenarios["normal_verified_then_undone"]
    assert normal["verified_transaction"]["status"] == "VERIFIED"
    assert normal["verified_transaction"]["created_event_ids"] == [
        "mem-event-0001",
        "mem-event-0002",
    ]
    assert normal["undone_transaction"]["status"] == "UNDONE"
    assert normal["final_event_ids"] == []

    conflict = scenarios["conflict_not_accepted"]
    assert conflict["preflight"]["conflict_result"]["has_conflict"] is True
    assert conflict["preflight"]["conflict_result"]["overlap_minutes"] == 30
    assert conflict["transaction"]["status"] == "WAITING_CONFIRMATION"

    create_failure = scenarios["second_create_failed"]
    assert create_failure["transaction"]["status"] == "ROLLED_BACK"
    assert create_failure["transaction"]["rollback_results"][0]["event_id"] == "mem-event-0001"
    assert create_failure["final_event_ids"] == []

    mismatch = scenarios["readback_mismatch"]
    assert mismatch["transaction"]["status"] == "ROLLED_BACK"
    assert mismatch["transaction"]["verification_results"][0]["mismatch_fields"] == ["title"]
    assert mismatch["final_event_ids"] == []
    assert data["google_calendar"]["real_call_verified"] is False

