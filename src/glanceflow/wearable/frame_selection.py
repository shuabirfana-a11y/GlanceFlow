from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

from glanceflow.ocr.base import OcrProvider
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.ocr.quality import inspect_image_quality
from glanceflow.wearable.models import CaptureResult, FrameScore, FrameSelectionResult


class DeterministicFrameSelector:
    weights = {
        "sharpness": 0.24,
        "brightness": 0.10,
        "resolution": 0.08,
        "ocr_confidence": 0.20,
        "text_amount": 0.16,
        "field_completeness": 0.22,
    }

    def __init__(self, provider: OcrProvider | None = None, minimum_score: float = 0.48) -> None:
        self.provider = provider or RapidOcrProvider()
        self.minimum_score = minimum_score

    def select(self, capture: CaptureResult) -> FrameSelectionResult:
        scores: list[FrameScore] = []
        for frame in capture.sampled_frames:
            scores.append(self._score(frame.frame_id, frame.image_path, frame.width, frame.height))
        eligible = [item for item in scores if item.eligible]
        if not eligible:
            return FrameSelectionResult(
                scores=scores,
                requires_recapture=True,
                reason="没有帧同时达到清晰度、文本量和综合得分阈值，请重新拍摄。",
            )
        best = max(eligible, key=lambda item: (item.total_score, -next(
            frame.timestamp_ms for frame in capture.sampled_frames if frame.frame_id == item.frame_id
        )))
        selected = next(frame for frame in capture.sampled_frames if frame.frame_id == best.frame_id)
        return FrameSelectionResult(
            selected_frame_id=best.frame_id,
            selected_image_path=selected.image_path,
            scores=scores,
            requires_recapture=False,
            reason="已按固定加权规则自动选择综合质量最高帧。",
        )

    def _score(self, frame_id: str, path: Path, width: int, height: int) -> FrameScore:
        quality = inspect_image_quality(path)
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        laplacian = float(cv2.Laplacian(image, cv2.CV_64F).var()) if image is not None else 0.0
        mean = float(image.mean()) if image is not None else 0.0
        sharpness = min(1.0, laplacian / 500.0)
        brightness = max(0.0, 1.0 - abs(mean - 170.0) / 170.0)
        resolution = min(1.0, (width * height) / (1280 * 720))
        lines = []
        confidence = 0.0
        reasons = list(quality.rejection_reasons)
        if quality.passed:
            ocr = self.provider.recognize(path, frame_id)
            if ocr.success:
                lines = ocr.evidence_lines
                confidence = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
            else:
                reasons.append(ocr.error_message or "OCR识别失败。")
        text = " ".join(line.text for line in lines)
        chars = sum(len(re.sub(r"\s+", "", line.text)) for line in lines)
        text_amount = min(1.0, chars / 45.0)
        signals = [
            bool(re.search(r"\d{1,2}月\d{1,2}日|\d{4}[-/.年]\d{1,2}", text)),
            bool(re.search(r"\d{1,2}[:：]\d{2}|上午|下午|晚上", text)),
            bool(re.search(r"地点|教室|楼|厅|馆|中心", text)),
            chars >= 12,
        ]
        completeness = sum(signals) / len(signals)
        components = {
            "sharpness": sharpness,
            "brightness": brightness,
            "resolution": resolution,
            "ocr_confidence": confidence,
            "text_amount": text_amount,
            "field_completeness": completeness,
        }
        total = sum(components[name] * weight for name, weight in self.weights.items())
        eligible = quality.passed and chars >= 10 and total >= self.minimum_score
        if chars < 10:
            reasons.append("可识别文本不足。")
        if total < self.minimum_score:
            reasons.append("综合选帧得分未达到阈值。")
        return FrameScore(
            frame_id=frame_id,
            eligible=eligible,
            total_score=round(total, 4),
            component_scores={key: round(value, 4) for key, value in components.items()},
            reasons=list(dict.fromkeys(reasons)),
            ocr_line_count=len(lines),
            ocr_character_count=chars,
        )
