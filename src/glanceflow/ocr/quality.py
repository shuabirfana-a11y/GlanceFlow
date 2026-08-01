from __future__ import annotations

from pathlib import Path

import cv2

from glanceflow.config import (
    OCR_MIN_TEXT_CHARACTERS,
    QUALITY_BLACK_MEAN_MAX,
    QUALITY_BLACK_STD_MAX,
    QUALITY_MIN_IMAGE_HEIGHT,
    QUALITY_MIN_IMAGE_WIDTH,
    QUALITY_MIN_LAPLACIAN_VARIANCE,
    SUPPORTED_IMAGE_EXTENSIONS,
)
from glanceflow.ocr.models import ImageQualityResult, QualityCheckResult
from glanceflow.ocr.preprocessing import decode_image, to_grayscale


def _check(check_id: str, passed: bool, message: str, value=None, threshold=None) -> QualityCheckResult:
    return QualityCheckResult(
        check_id=check_id,
        passed=passed,
        message=message,
        measured_value=value,
        threshold=threshold,
    )


def inspect_image_quality(image_path: Path) -> ImageQualityResult:
    path = Path(image_path)
    checks: list[QualityCheckResult] = []

    exists = path.is_file()
    checks.append(_check("GF-IMG-EXISTS", exists, "图片文件存在。" if exists else "图片文件不存在。"))
    extension_ok = path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    checks.append(
        _check(
            "GF-IMG-FORMAT",
            extension_ok,
            "图片格式受支持。" if extension_ok else "图片格式不受支持。",
            path.suffix.lower() or "（无扩展名）",
            ", ".join(sorted(SUPPORTED_IMAGE_EXTENSIONS)),
        )
    )
    if not exists or not extension_ok:
        reasons = [item.message for item in checks if not item.passed]
        return ImageQualityResult(passed=False, image_path=path, checks=checks, rejection_reasons=reasons)

    try:
        image = decode_image(path)
    except (OSError, ValueError) as exc:
        checks.append(_check("GF-IMG-DECODE", False, str(exc)))
        return ImageQualityResult(
            passed=False,
            image_path=path,
            checks=checks,
            rejection_reasons=[str(exc)],
        )

    height, width = image.shape[:2]
    checks.append(_check("GF-IMG-DECODE", True, "图片解码成功。"))
    resolution_ok = width >= QUALITY_MIN_IMAGE_WIDTH and height >= QUALITY_MIN_IMAGE_HEIGHT
    checks.append(
        _check(
            "GF-IMG-RESOLUTION",
            resolution_ok,
            "图片分辨率满足初始阈值。" if resolution_ok else "图片分辨率过低。",
            f"{width}x{height}",
            f">={QUALITY_MIN_IMAGE_WIDTH}x{QUALITY_MIN_IMAGE_HEIGHT}",
        )
    )

    gray = to_grayscale(image)
    mean, std = cv2.meanStdDev(gray)
    gray_mean = float(mean[0, 0])
    gray_std = float(std[0, 0])
    not_black = not (gray_mean <= QUALITY_BLACK_MEAN_MAX and gray_std <= QUALITY_BLACK_STD_MAX)
    checks.append(
        _check(
            "GF-IMG-NOT-BLACK",
            not_black,
            "图片不是空白全黑画面。" if not_black else "图片为空或近似全黑。",
            round(gray_mean, 2),
            f"mean>{QUALITY_BLACK_MEAN_MAX} or std>{QUALITY_BLACK_STD_MAX}",
        )
    )

    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    sharp_enough = laplacian_variance >= QUALITY_MIN_LAPLACIAN_VARIANCE
    checks.append(
        _check(
            "GF-IMG-SHARPNESS",
            sharp_enough,
            "图片清晰度满足初始阈值。" if sharp_enough else "图片明显模糊。",
            round(laplacian_variance, 2),
            QUALITY_MIN_LAPLACIAN_VARIANCE,
        )
    )
    reasons = [item.message for item in checks if not item.passed]
    return ImageQualityResult(
        passed=not reasons,
        image_path=path,
        image_width=width,
        image_height=height,
        checks=checks,
        rejection_reasons=reasons,
    )


def add_ocr_text_check(quality: ImageQualityResult, texts: list[str]) -> ImageQualityResult:
    character_count = sum(len(text.strip()) for text in texts)
    passed = character_count >= OCR_MIN_TEXT_CHARACTERS
    check = _check(
        "GF-OCR-HAS-TEXT",
        passed,
        "OCR识别到有效文本。" if passed else "OCR未识别到有效文本。",
        character_count,
        OCR_MIN_TEXT_CHARACTERS,
    )
    checks = [*quality.checks, check]
    reasons = [item.message for item in checks if not item.passed]
    return quality.model_copy(update={"passed": not reasons, "checks": checks, "rejection_reasons": reasons})

