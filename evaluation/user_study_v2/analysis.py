from __future__ import annotations

import csv
from pathlib import Path


def analyze(path: Path = Path(__file__).with_name("record_template.csv")) -> dict[str, object]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("participant_code") or "").strip()]
    participants = sorted({row["participant_code"] for row in rows})
    if not participants:
        return {"STATUS": "WAITING_FOR_DATA", "PARTICIPANT_COUNT": 0, "message": "尚未执行"}
    if any(row.get("consent_confirmed", "").lower() != "true" for row in rows):
        raise ValueError("all analyzed records require confirmed consent")
    return {"STATUS": "EXECUTED", "PARTICIPANT_COUNT": len(participants), "TASK_RECORD_COUNT": len(rows)}


if __name__ == "__main__":
    for key, value in analyze().items():
        print(f"{key}={value}")
