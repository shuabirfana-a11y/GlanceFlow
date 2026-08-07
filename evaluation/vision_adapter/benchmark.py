from __future__ import annotations

import json
from pathlib import Path

from glanceflow.vision.paddleocr_adapter import PaddleOCRAdapter
from glanceflow.vision.rapidocr_adapter import RapidOCRAdapter


def benchmark_status() -> dict:
    rapid = RapidOCRAdapter()
    paddle = PaddleOCRAdapter()
    return {
        "rapidocr": {"status": "AVAILABLE" if rapid.healthcheck() else "UNAVAILABLE", "version": rapid.get_version()},
        "paddleocr": {
            "status": "AVAILABLE_NOT_RUN" if paddle.healthcheck() else "NOT_EVALUATED",
            "version": paddle.get_version(),
            "reason": None if paddle.healthcheck() else "optional dependency is not installed",
        },
        "production_default_changed": False,
    }


def main() -> None:
    output = Path("outputs/evaluation/vision_adapter/benchmark_status.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(benchmark_status(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
