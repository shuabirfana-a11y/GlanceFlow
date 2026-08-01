from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
POSTERS = ROOT / "data" / "synthetic_posters"
OUTPUT = ROOT / "data" / "synthetic_videos"
GROUND_TRUTH = ROOT / "data" / "ground_truth" / "synthetic_videos.json"
FPS = 5
FRAME_COUNT = 15


SCENARIOS = {
    "01_clear_notice.mp4": ("01_valid_event.png", "clear", "READY_TO_CONFIRM"),
    "02_blur_to_clear.mp4": ("01_valid_event.png", "blur_to_clear", "READY_TO_CONFIRM"),
    "03_always_blurred.mp4": ("09_blurred_image.png", "always_blur", "RECAPTURE_REQUIRED"),
    "04_event_with_deadline.mp4": ("02_event_with_deadline.png", "clear", "READY_TO_CONFIRM"),
    "05_weekday_contradiction.mp4": ("03_weekday_contradiction.png", "clear", "CONTRADICTION_BLOCKED"),
    "06_unresolved_time.mp4": ("04_unresolved_time.png", "clear", "NEED_USER_INPUT"),
    "07_ambiguous_times.mp4": ("10_ambiguous_times.png", "clear", "CONTRADICTION_BLOCKED"),
    "08_moving_notice.mp4": ("01_valid_event.png", "moving", "READY_TO_CONFIRM"),
}


def _frame(image: np.ndarray, mode: str, index: int, rng: np.random.Generator) -> np.ndarray:
    height, width = image.shape[:2]
    result = image.copy()
    if mode == "blur_to_clear" and index < 8:
        kernel = 31 - index * 2
        kernel += 1 - kernel % 2
        result = cv2.GaussianBlur(result, (max(9, kernel), max(9, kernel)), 0)
    elif mode == "always_blur":
        result = cv2.GaussianBlur(result, (31, 31), 0)
    angle = float(rng.uniform(-0.35, 0.35))
    dx = float(rng.uniform(-2.0, 2.0))
    dy = float(rng.uniform(-2.0, 2.0))
    if mode == "moving":
        angle = float(rng.uniform(-2.2, 2.2))
        dx = float(rng.uniform(-18, 18))
        dy = float(rng.uniform(-12, 12))
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    matrix[:, 2] += (dx, dy)
    return cv2.warpAffine(result, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)


def generate() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(20260801)
    records = []
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    for filename, (poster_name, mode, expected_status) in SCENARIOS.items():
        source = cv2.imdecode(np.fromfile(POSTERS / poster_name, dtype=np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise RuntimeError(f"无法读取合成海报：{poster_name}")
        height, width = source.shape[:2]
        path = OUTPUT / filename
        writer = cv2.VideoWriter(str(path), fourcc, FPS, (width, height))
        if not writer.isOpened():
            raise RuntimeError(f"无法创建视频：{path}")
        try:
            for index in range(FRAME_COUNT):
                writer.write(_frame(source, mode, index, rng))
        finally:
            writer.release()
        records.append({
            "video": filename,
            "source_poster": poster_name,
            "transformation": mode,
            "expected_pipeline_status": expected_status,
            "fps": FPS,
            "frame_count": FRAME_COUNT,
            "duration_ms": int(FRAME_COUNT / FPS * 1000),
            "synthetic_only": True,
        })
    document = {"seed": 20260801, "notice": "全部素材均为程序生成，不含真实校园数据。", "scenarios": records}
    GROUND_TRUTH.parent.mkdir(parents=True, exist_ok=True)
    GROUND_TRUTH.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return document


if __name__ == "__main__":
    result = generate()
    print(f"已生成 {len(result['scenarios'])} 段合成短视频。")
