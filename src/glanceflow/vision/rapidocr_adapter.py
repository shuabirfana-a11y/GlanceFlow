from pathlib import Path

from glanceflow.config import OCR_PROVIDER_VERSION
from glanceflow.ocr.models import OcrResult
from glanceflow.ocr.provider import RapidOcrProvider


class RapidOCRAdapter:
    def __init__(self, provider: RapidOcrProvider | None = None) -> None:
        self.provider = provider or RapidOcrProvider()

    def recognize(self, image_path: Path, source_frame_id: str) -> OcrResult:
        return self.provider.recognize(image_path, source_frame_id)

    def healthcheck(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    def get_version(self) -> str:
        return OCR_PROVIDER_VERSION

    def get_capabilities(self) -> set[str]:
        return {"text", "bbox", "confidence", "local_cpu", "chinese"}
