from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evaluation" / "dataset"
IMAGE_DIR = DATASET / "images"
VIDEO_DIR = DATASET / "videos"
ANNOTATION_DIR = DATASET / "annotations"
POSTERS = ROOT / "data" / "synthetic_posters"
SEED = 20260801


SPECS = {
    "normal": dict(source="01_valid_event.png", notice="EVENT_NOTICE", title="创新创业竞赛宣讲", start="2026-08-07T14:00:00+08:00", location="科技馆报告厅", deadline=None, status="READY_TO_CONFIRM", reason=None, executable=True),
    "deadline": dict(source="02_event_with_deadline.png", notice="EVENT_WITH_DEADLINE", title="实验室招募说明会", start="2026-08-08T15:00:00+08:00", location="理科楼A201", deadline="2026-08-07T20:00:00+08:00", status="READY_TO_CONFIRM", reason=None, executable=True),
    "weekday": dict(source="03_weekday_contradiction.png", notice="EVENT_NOTICE", title="机器人竞赛培训", start="2026-08-10T14:00:00+08:00", location="综合实验大厅", deadline=None, status="CONTRADICTION_BLOCKED", reason="DATE_WEEKDAY_CONTRADICTION", executable=False),
    "unresolved": dict(source="04_unresolved_time.png", notice="EVENT_NOTICE", title="摄影社交流活动", start=None, location="大学生活动中心", deadline=None, status="NEED_USER_INPUT", reason="UNRESOLVED_TIME", executable=False),
    "missing_location": dict(source="05_missing_location.png", notice="EVENT_NOTICE", title="学术写作讲座", start="2026-08-12T10:00:00+08:00", location=None, deadline=None, status="NEED_USER_INPUT", reason="MISSING_LOCATION", executable=False),
    "expired": dict(source="06_expired_event.png", notice="EVENT_NOTICE", title="旧海报讲座", start="2026-07-31T14:00:00+08:00", location="图书馆报告厅", deadline=None, status="CONTRADICTION_BLOCKED", reason="EXPIRED_EVENT", executable=False),
    "deadline_error": dict(source="07_deadline_after_event.png", notice="EVENT_WITH_DEADLINE", title="创业训练营", start="2026-08-13T09:00:00+08:00", location="创新大楼301", deadline="2026-08-14T20:00:00+08:00", status="CONTRADICTION_BLOCKED", reason="DEADLINE_AFTER_EVENT", executable=False),
    "ambiguous": dict(source="10_ambiguous_times.png", notice="EVENT_NOTICE", title="多场次交流会", start=None, location="国际交流中心", deadline=None, status="CONTRADICTION_BLOCKED", reason="MULTIPLE_EVENT_TIMES", executable=False),
    "low_resolution": dict(source="08_low_resolution.png", notice="EVENT_NOTICE", title="低分辨率通知", start="2026-08-14T14:00:00+08:00", location="就业中心205", deadline=None, status="RECAPTURE_REQUIRED", reason="LOW_RESOLUTION", executable=False),
    "blurred": dict(source="09_blurred_image.png", notice="EVENT_NOTICE", title="模糊画面讲座", start="2026-08-15T14:00:00+08:00", location="综合楼报告厅", deadline=None, status="RECAPTURE_REQUIRED", reason="BLURRED_IMAGE", executable=False),
    "low_confidence": dict(source="01_valid_event.png", notice="EVENT_NOTICE", title="创新创业竞赛宣讲", start="2026-08-07T14:00:00+08:00", location="科技馆报告厅", deadline=None, status="RECAPTURE_REQUIRED", reason="LOW_EVIDENCE_CONFIDENCE", executable=False),
}


def _transform(image: np.ndarray, index: int, *, low_confidence: bool = False) -> np.ndarray:
    if low_confidence:
        kernel_size = 13 + 2 * (index % 2)
        kernel = np.zeros((kernel_size, kernel_size), dtype=np.float32)
        kernel[kernel_size // 2, :] = 1.0 / kernel_size
        return cv2.filter2D(image, -1, kernel)
    alpha = (0.96, 1.0, 1.04, 0.98)[index % 4]
    beta = (-5, 0, 4, 2)[index % 4]
    adjusted = cv2.convertScaleAbs(image, alpha=alpha, beta=beta)
    height, width = adjusted.shape[:2]
    angle = (-0.35, 0.2, 0.4, -0.15)[index % 4]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    return cv2.warpAffine(adjusted, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)


def _write_video(path: Path, source: np.ndarray, variant: int, *, always_blur: bool = False) -> None:
    height, width = source.shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 5, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"无法创建视频：{path}")
    rng = np.random.default_rng(SEED + variant)
    try:
        for frame_index in range(15):
            frame = source.copy()
            if always_blur:
                frame = cv2.GaussianBlur(frame, (31, 31), 0)
            elif variant % 2 and frame_index < 7:
                frame = cv2.GaussianBlur(frame, (15, 15), 0)
            matrix = cv2.getRotationMatrix2D((width / 2, height / 2), float(rng.uniform(-0.7, 0.7)), 1.0)
            matrix[:, 2] += (float(rng.uniform(-4, 4)), float(rng.uniform(-3, 3)))
            writer.write(cv2.warpAffine(frame, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE))
    finally:
        writer.release()


def generate() -> dict:
    for directory in (IMAGE_DIR, VIDEO_DIR, ANNOTATION_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    cases: list[tuple[str, str, int, str, str, str]] = []
    cases += [("normal", "normal_executable", i, "image", "NONE", "NONE") for i in range(8)]
    cases += [("normal", "normal_executable", i, "video", "NONE", "NONE") for i in range(2)]
    cases += [("deadline", "event_with_deadline", i, "image", "NONE", "NONE") for i in range(6)]
    cases += [("deadline", "event_with_deadline", i, "video", "NONE", "NONE") for i in range(2)]
    cases += [("weekday", "weekday_contradiction", i, "image", "NONE", "NONE") for i in range(4)]
    cases += [("unresolved", "ambiguous_time_expression", i, "image", "NONE", "NONE") for i in range(4)]
    cases += [("missing_location", "missing_location", i, "image", "NONE", "NONE") for i in range(3)]
    cases += [("expired", "expired_event", i, "image", "NONE", "NONE") for i in range(3)]
    cases += [("deadline_error", "invalid_deadline_order", i, "image", "NONE", "NONE") for i in range(2)]
    cases += [("ambiguous", "multiple_time_ambiguity", i, "image", "NONE", "NONE") for i in range(2)]
    cases += [("low_resolution", "low_quality", 0, "image", "NONE", "NONE"), ("blurred", "low_quality", 1, "image", "NONE", "NONE"), ("low_confidence", "low_quality", 2, "image", "NONE", "NONE"), ("blurred", "low_quality", 3, "video", "NONE", "NONE")]
    cases += [("normal", "duplicate_or_conflict", 0, "image", "DUPLICATE", "NONE"), ("normal", "duplicate_or_conflict", 1, "image", "DUPLICATE", "NONE"), ("normal", "duplicate_or_conflict", 2, "image", "CONFLICT", "NONE"), ("normal", "duplicate_or_conflict", 3, "image", "CONFLICT", "NONE")]
    cases += [("normal", "provider_fault", 0, "image", "NONE", "READBACK_MISMATCH"), ("deadline", "provider_fault", 1, "image", "NONE", "SECOND_CREATE_FAILURE")]

    samples = []
    for number, (spec_name, category, variant, media, context, fault) in enumerate(cases, start=1):
        sample_id = f"GF-EVAL-{number:03d}"
        spec = dict(SPECS[spec_name])
        if context == "DUPLICATE":
            spec.update(status="CONTRADICTION_BLOCKED", reason="DUPLICATE_NOTICE", executable=False)
        elif context == "CONFLICT":
            spec.update(status="READY_TO_CONFIRM", reason="CONFLICT_REQUIRES_CONFIRMATION", executable=False)
        source = cv2.imdecode(np.fromfile(POSTERS / spec["source"], dtype=np.uint8), cv2.IMREAD_COLOR)
        if source is None:
            raise RuntimeError(f"无法读取：{spec['source']}")
        suffix = ".mp4" if media == "video" else ".png"
        relative = Path("evaluation") / "dataset" / ("videos" if media == "video" else "images") / f"{sample_id}{suffix}"
        output = ROOT / relative
        if media == "video":
            _write_video(output, source, variant + number, always_blur=spec_name == "blurred")
        else:
            transformed = source.copy() if category == "provider_fault" else _transform(source, variant + number, low_confidence=spec_name == "low_confidence")
            encoded, data = cv2.imencode(".png", transformed)
            if not encoded:
                raise RuntimeError(f"无法编码：{output}")
            data.tofile(output)
        sample = {
            "sample_id": sample_id,
            "input_path": str(relative).replace("\\", "/"),
            "media_type": media.upper(),
            "source_type": "ARTIFICIAL_FIRST_PERSON_VIDEO" if media == "video" else "ARTIFICIAL_POSTER",
            "category": category,
            "expected_notice_type": spec["notice"],
            "expected_title": spec["title"],
            "expected_event_start": spec["start"],
            "expected_location": spec["location"],
            "expected_deadline": spec["deadline"],
            "expected_safety_status": spec["status"],
            "expected_failure_reason": spec["reason"],
            "is_executable": spec["executable"],
            "scenario_tags": [category, spec_name, media.lower(), context.lower(), fault.lower()],
            "synthetic": True,
            "annotation_notes": "由固定种子脚本从人工测试海报生成；不是实拍校园数据。" + (" 评测协议不提供冲突二次确认。" if context == "CONFLICT" else ""),
            "existing_context": context,
            "fault_plan": fault,
        }
        samples.append(sample)
        (ANNOTATION_DIR / f"{sample_id}.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = dict(sorted(Counter(sample["category"] for sample in samples).items()))
    manifest = {
        "dataset_id": "glanceflow-stage5-synthetic-v1",
        "version": "1.0.0",
        "generated_with_seed": SEED,
        "captured_at": "2026-08-01T09:00:00+08:00",
        "simulator_environment": "Windows local CPU simulator; not real glasses latency",
        "contains_team_capture": False,
        "consent_records_required": False,
        "sample_count": len(samples),
        "category_counts": counts,
        "samples": samples,
    }
    (DATASET / "dataset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = generate()
    print(f"已生成 {result['sample_count']} 个评测案例：{result['category_counts']}")
