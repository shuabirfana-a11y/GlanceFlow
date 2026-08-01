import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PROJECT_ROOT / "examples"
POSTERS = PROJECT_ROOT / "data" / "synthetic_posters"


def run_cli(
    input_path: Path,
    cwd: Path,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-m", "glanceflow.cli"]
    if extra_args:
        command.extend([extra_args[0], str(input_path), *extra_args[1:]])
    else:
        command.append(str(input_path))
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        capture_output=True,
        env=environment,
        check=False,
    )


def test_cli_single_file(tmp_path):
    result = run_cli(EXAMPLES / "01_valid_event.json", tmp_path)
    assert result.returncode == 0, result.stderr
    assert "GF-TIME-004" in result.stdout
    assert "最终安全状态：READY_TO_CONFIRM" in result.stdout
    assert "是否允许确认：是" in result.stdout


def test_cli_batch_run(tmp_path):
    result = run_cli(EXAMPLES, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "最终安全状态：NEED_USER_INPUT" in result.stdout
    assert "最终安全状态：RECAPTURE_REQUIRED" in result.stdout
    assert "最终安全状态：CONTRADICTION_BLOCKED" in result.stdout
    assert "GF-DUPLICATE-001" in result.stdout


def test_batch_output_json_is_generated(tmp_path):
    result = run_cli(EXAMPLES, tmp_path)
    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "outputs" / "stage1_results.json"
    assert output_path.is_file()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data) == 9
    decisions = {Path(item["source_file"]).name: item["decision"] for item in data}
    assert decisions["01_valid_event.json"]["status"] == "READY_TO_CONFIRM"
    assert decisions["03_missing_location.json"]["status"] == "NEED_USER_INPUT"
    assert decisions["08_low_confidence.json"]["status"] == "RECAPTURE_REQUIRED"
    assert decisions["09_duplicate_notification.json"]["status"] == "CONTRADICTION_BLOCKED"
    duplicate_failures = {
        rule["rule_id"]
        for rule in decisions["09_duplicate_notification.json"]["rule_results"]
        if not rule["passed"]
    }
    assert "GF-DUPLICATE-001" in duplicate_failures


def test_cli_image_single_file(tmp_path):
    result = run_cli(
        POSTERS / "01_valid_event.png",
        tmp_path,
        extra_args=["extract-image", "--captured-at", "2026-08-01T09:00:00+08:00"],
    )
    assert result.returncode == 0, result.stderr
    assert "frame-01_valid_event-ocr-0002" in result.stdout
    assert "字段证据绑定" in result.stdout
    assert "GF-TIME-004" in result.stdout
    assert "最终安全状态：READY_TO_CONFIRM" in result.stdout


def test_cli_image_directory_and_stage2_output(tmp_path):
    result = run_cli(
        POSTERS,
        tmp_path,
        extra_args=["extract-image", "--captured-at", "2026-08-01T09:00:00+08:00"],
    )
    assert result.returncode == 0, result.stderr
    output_path = tmp_path / "outputs" / "stage2_results.json"
    assert output_path.is_file()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(data) == 10
    statuses = {Path(item["source_file"]).name: item["result"]["final_status"] for item in data}
    assert statuses["01_valid_event.png"] == "READY_TO_CONFIRM"
    assert statuses["04_unresolved_time.png"] == "NEED_USER_INPUT"
    assert statuses["09_blurred_image.png"] == "RECAPTURE_REQUIRED"
    assert statuses["10_ambiguous_times.png"] == "CONTRADICTION_BLOCKED"
