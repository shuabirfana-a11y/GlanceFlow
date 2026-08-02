from __future__ import annotations

import csv
import json
from pathlib import Path


RECORD_PATH = Path(__file__).with_name("record_template.csv")
REQUIRED_FIELDS = {
    "participant_id", "session_date", "task_id", "completed",
    "completion_time_seconds", "confirmation_count", "recapture_count",
    "misoperation", "hud_understood", "trust_rating", "burden_rating",
    "willing_to_continue", "notes",
}


def analyze(path: Path = RECORD_PATH) -> dict:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != REQUIRED_FIELDS:
            raise ValueError("记录模板字段不完整。")
        rows = [row for row in reader if any(value.strip() for value in row.values())]
    if not rows:
        return {
            "status": "尚未执行",
            "participants": 0,
            "sessions": 0,
            "results_available": False,
            "summary": "没有真实记录，不计算均值、比例或量表结果。",
        }
    participants = sorted({row["participant_id"] for row in rows if row["participant_id"]})
    sessions = sorted({(row["participant_id"], row["session_date"]) for row in rows})
    return {
        "status": "已有真实记录，需人工核验同意书后分析",
        "participants": len(participants),
        "sessions": len(sessions),
        "results_available": True,
        "summary": "脚本只完成记录计数；评分统计须在同意与数据质量复核后另行执行。",
    }


if __name__ == "__main__":
    print(json.dumps(analyze(), ensure_ascii=False, indent=2))
