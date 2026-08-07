from __future__ import annotations

import hashlib
import json
from pathlib import Path
from time import perf_counter

from glanceflow.domain.models import EvidenceLine
from glanceflow.ocr.models import OcrResult
from glanceflow.ocr.preprocessing import decode_image


class PaddleOCRAdapter:
    """Optional adapter. Importing GlanceFlow never imports PaddleOCR."""

    def __init__(self) -> None:
        self._engine = None

    def healthcheck(self) -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except Exception:
            return False

    def get_version(self) -> str:
        if not self.healthcheck():
            return "SDK_UNAVAILABLE"
        from importlib.metadata import version
        try:
            return version("paddleocr")
        except Exception:
            return "UNKNOWN_INSTALLED_VERSION"

    def get_capabilities(self) -> set[str]:
        if not self.healthcheck():
            return set()
        return {"text", "bbox", "confidence", "orientation", "local_cpu", "chinese"}

    def recognize(self, image_path: Path, source_frame_id: str) -> OcrResult:
        path = Path(image_path)
        started = perf_counter()
        if not self.healthcheck():
            return OcrResult(
                source_frame_id=source_frame_id, image_path=path, image_width=0,
                image_height=0, provider_name="PaddleOCR", provider_version="SDK_UNAVAILABLE",
                processing_time_ms=0, success=False,
                error_message="PaddleOCR optional dependency is not installed",
            )
        try:
            from paddleocr import PaddleOCR

            image = decode_image(path)
            height, width = image.shape[:2]
            if self._engine is None:
                self._engine = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    device="cpu",
                )
            lines: list[EvidenceLine] = []
            for result in self._engine.predict(str(path)):
                payload = result.json
                if callable(payload):
                    payload = payload()
                if isinstance(payload, str):
                    payload = json.loads(payload)
                data = payload.get("res", payload)
                for text, score, polygon in zip(
                    data.get("rec_texts", []),
                    data.get("rec_scores", []),
                    data.get("rec_polys", []),
                    strict=False,
                ):
                    xs = [float(point[0]) for point in polygon]
                    ys = [float(point[1]) for point in polygon]
                    lines.append(EvidenceLine(
                        line_id=f"{source_frame_id}-ocr-{len(lines) + 1:04d}",
                        text=str(text), confidence=float(score), source_frame_id=source_frame_id,
                        bbox=(min(xs), min(ys), max(xs), max(ys)),
                    ))
            return OcrResult(
                source_frame_id=source_frame_id, image_path=path,
                image_width=width, image_height=height,
                image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                evidence_lines=lines, provider_name="PaddleOCR",
                provider_version=self.get_version(),
                processing_time_ms=(perf_counter() - started) * 1000,
                success=True,
            )
        except Exception as exc:
            return OcrResult(
                source_frame_id=source_frame_id, image_path=path,
                image_width=0, image_height=0, provider_name="PaddleOCR",
                provider_version=self.get_version(),
                processing_time_ms=(perf_counter() - started) * 1000,
                success=False, error_message=f"PaddleOCR failed: {type(exc).__name__}: {exc}",
            )
