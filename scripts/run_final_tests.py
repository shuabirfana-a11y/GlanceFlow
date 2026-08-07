from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/final/test_summary.json"


def main() -> int:
    command = [sys.executable, "-m", "pytest", "-q", "--basetemp=work/pytest-final-freeze", "-p", "no:cacheprovider"]
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end="")
    passed = re.search(r"(\d+) passed", result.stdout)
    skipped = re.search(r"(\d+) skipped", result.stdout)
    failed = re.search(r"(\d+) failed", result.stdout)
    payload = {
        "passed": int(passed.group(1)) if passed else 0,
        "skipped": int(skipped.group(1)) if skipped else 0,
        "failed": int(failed.group(1)) if failed else (0 if result.returncode == 0 else 1),
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "command": "python -m pytest -q",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__": raise SystemExit(main())
