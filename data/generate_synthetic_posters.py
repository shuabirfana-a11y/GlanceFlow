"""Generate deterministic artificial campus-notice fixtures for Stage 2.

These images are test material only. They are not notices from any real school.
No font file is copied: the script references an installed Windows font.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


SEED = 20260801
ROOT = Path(__file__).resolve().parent
POSTER_DIR = ROOT / "synthetic_posters"
TRUTH_DIR = ROOT / "ground_truth"
FONT_REGULAR = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BOLD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
CAPTURED_AT = "2026-08-01T09:00:00+08:00"


SCENARIOS = [
    {
        "name": "01_valid_event",
        "lines": ["活动标题：创新创业竞赛宣讲", "2026年8月7日 星期五 14:00", "地点：科技馆报告厅"],
        "expected_status": "READY_TO_CONFIRM",
        "expected": {"title": "创新创业竞赛宣讲", "event_start": "2026-08-07T14:00:00+08:00", "location": "科技馆报告厅"},
    },
    {
        "name": "02_event_with_deadline",
        "lines": [
            "活动标题：实验室招募说明会",
            "2026年8月8日 星期六 15:00",
            "地点：理科楼A201",
            "报名截止：2026年8月7日 20:00",
            "截止动作：完成实验室报名",
        ],
        "expected_status": "READY_TO_CONFIRM",
        "expected": {"title": "实验室招募说明会", "event_start": "2026-08-08T15:00:00+08:00", "deadline": "2026-08-07T20:00:00+08:00"},
    },
    {
        "name": "03_weekday_contradiction",
        "lines": ["活动标题：机器人竞赛培训", "2026年8月10日 星期二 14:00", "地点：综合实验大厅"],
        "expected_status": "CONTRADICTION_BLOCKED",
        "expected_rule_id": "GF-TIME-004",
    },
    {
        "name": "04_unresolved_time",
        "lines": ["活动标题：摄影社交流活动", "活动时间：周五下午", "地点：大学生活动中心"],
        "expected_status": "NEED_USER_INPUT",
        "expected_issue_id": "GF-EXTRACT-TIME-MISSING",
    },
    {
        "name": "05_missing_location",
        "lines": ["活动标题：学术写作讲座", "2026年8月12日 星期三 10:00"],
        "expected_status": "NEED_USER_INPUT",
        "expected_rule_id": "GF-FIELD-002",
    },
    {
        "name": "06_expired_event",
        "lines": ["活动标题：旧海报讲座", "2026年7月31日 星期五 14:00", "地点：图书馆报告厅"],
        "expected_status": "CONTRADICTION_BLOCKED",
        "expected_rule_id": "GF-TIME-003",
    },
    {
        "name": "07_deadline_after_event",
        "lines": [
            "活动标题：创业训练营",
            "2026年8月13日 星期四 09:00",
            "地点：创新大楼301",
            "报名截止：2026年8月14日 20:00",
            "截止动作：完成训练营报名",
        ],
        "expected_status": "CONTRADICTION_BLOCKED",
        "expected_rule_id": "GF-DEADLINE-002",
    },
    {
        "name": "08_low_resolution",
        "lines": ["活动标题：低分辨率通知", "2026年8月14日 星期五 14:00", "地点：就业中心205"],
        "expected_status": "RECAPTURE_REQUIRED",
        "expected_quality_check": "GF-IMG-RESOLUTION",
        "size": [420, 280],
    },
    {
        "name": "09_blurred_image",
        "lines": ["活动标题：模糊画面讲座", "2026年8月15日 星期六 14:00", "地点：综合楼报告厅"],
        "expected_status": "RECAPTURE_REQUIRED",
        "expected_quality_check": "GF-IMG-SHARPNESS",
        "blur_radius": 12,
    },
    {
        "name": "10_ambiguous_times",
        "lines": [
            "活动标题：多场次交流会",
            "2026年8月16日 星期日 10:00",
            "2026年8月17日 星期一 15:00",
            "地点：国际交流中心",
        ],
        "expected_status": "CONTRADICTION_BLOCKED",
        "expected_issue_id": "GF-EXTRACT-TIME-AMBIGUOUS",
    },
]


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.is_file():
        raise FileNotFoundError(f"所需系统字体不存在：{path}")
    return ImageFont.truetype(str(path), size)


def render_poster(lines: list[str], size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    scale = width / 1400
    badge_font = _font(FONT_REGULAR, max(15, round(28 * scale)))
    body_font = _font(FONT_BOLD, max(20, round(52 * scale)))
    footer_font = _font(FONT_REGULAR, max(13, round(24 * scale)))
    margin = max(24, round(80 * scale))
    draw.rounded_rectangle(
        (margin, max(18, round(35 * scale)), width - margin, max(58, round(92 * scale))),
        radius=max(8, round(16 * scale)),
        fill=(232, 241, 250),
    )
    draw.text((margin + 18, max(23, round(43 * scale))), "人工构造测试素材", font=badge_font, fill=(26, 71, 112))
    start_y = max(78, round(150 * scale))
    line_gap = max(43, round(112 * scale))
    for index, text in enumerate(lines):
        draw.text((margin, start_y + index * line_gap), text, font=body_font, fill=(12, 18, 24))
    footer = "仅用于 GlanceFlow 测试，并非真实学校通知"
    draw.text((margin, height - max(38, round(58 * scale))), footer, font=footer_font, fill=(92, 102, 112))
    return image


def main() -> None:
    random.seed(SEED)
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    for scenario in SCENARIOS:
        size = tuple(scenario.get("size", [1400, 900]))
        image = render_poster(scenario["lines"], size)
        if scenario.get("blur_radius"):
            image = image.filter(ImageFilter.GaussianBlur(radius=scenario["blur_radius"]))
        image_path = POSTER_DIR / f"{scenario['name']}.png"
        image.save(image_path, format="PNG", optimize=False)

        truth = {
            "artificial_test_material": True,
            "not_a_real_school_notice": True,
            "random_seed": SEED,
            "font_reference": str(FONT_BOLD),
            "captured_at": CAPTURED_AT,
            "timezone": "Asia/Shanghai",
            "image_file": image_path.name,
            **{key: value for key, value in scenario.items() if key not in {"size", "blur_radius"}},
        }
        (TRUTH_DIR / f"{scenario['name']}.json").write_text(
            json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(f"Generated {len(SCENARIOS)} synthetic posters in {POSTER_DIR}")


if __name__ == "__main__":
    main()
