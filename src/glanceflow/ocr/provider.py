from __future__ import annotations

import hashlib
from pathlib import Path
from time import perf_counter
from typing import Any

from glanceflow.config import OCR_PROVIDER_NAME, OCR_PROVIDER_VERSION
from glanceflow.domain.models import EvidenceLine
from glanceflow.ocr.models import OcrResult
from glanceflow.ocr.preprocessing import decode_image


class RapidOcrProvider:
    """Local CPU OCR provider backed by bundled RapidOCR ONNX models."""

    def __init__(self, engine: Any | None = None) -> None:
        self._engine = engine

    def _get_engine(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
        return self._engine

    def recognize(self, image_path: Path, source_frame_id: str) -> OcrResult:
        path = Path(image_path)
        started = perf_counter()
        width = 0
        height = 0
        try:
            image = decode_image(path)
            source_image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            height, width = image.shape[:2]
            raw_result, _ = self._get_engine()(image)
            parsed: list[tuple[list[list[float]], str, float]] = []
            warnings: list[str] = []
            for raw in raw_result or []:
                if len(raw) < 3:
                    warnings.append("OCR提供器返回了不完整结果，已忽略。")
                    continue
                points, text, confidence = raw[0], str(raw[1]), float(raw[2])
                if len(points) != 4 or not text.strip():
                    warnings.append("OCR提供器返回了空文本或非法坐标，已忽略。")
                    continue
                parsed.append((points, text, max(0.0, min(1.0, confidence))))
            parsed.sort(key=lambda item: (min(point[1] for point in item[0]), min(point[0] for point in item[0])))

            evidence_lines: list[EvidenceLine] = []
            for index, (points, text, confidence) in enumerate(parsed, start=1):
                xs = [float(point[0]) for point in points]
                ys = [float(point[1]) for point in points]
                evidence_lines.append(
                    EvidenceLine(
                        line_id=f"{source_frame_id}-ocr-{index:04d}",
                        text=text,
                        confidence=confidence,
                        source_frame_id=source_frame_id,
                        bbox=(min(xs), min(ys), max(xs), max(ys)),
                    )
                )
            return OcrResult(
                source_frame_id=source_frame_id,
                image_path=path,
                image_width=width,
                image_height=height,
                image_sha256=source_image_hash,
                evidence_lines=evidence_lines,
                provider_name=OCR_PROVIDER_NAME,
                provider_version=OCR_PROVIDER_VERSION,
                processing_time_ms=(perf_counter() - started) * 1000,
                warnings=warnings,
                success=True,
            )
        except Exception as exc:  # Provider boundary must convert engine failures to data.
            return OcrResult(
                source_frame_id=source_frame_id,
                image_path=path,
                image_width=width,
                image_height=height,
                provider_name=OCR_PROVIDER_NAME,
                provider_version=OCR_PROVIDER_VERSION,
                processing_time_ms=(perf_counter() - started) * 1000,
                success=False,
                error_message=f"OCR识别失败：{type(exc).__name__}: {exc}",
            )
