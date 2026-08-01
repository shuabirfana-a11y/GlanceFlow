from pathlib import Path
from typing import Protocol

from glanceflow.ocr.models import OcrResult


class OcrProvider(Protocol):
    def recognize(self, image_path: Path, source_frame_id: str) -> OcrResult:
        """Recognize real OCR lines and coordinates from one local image."""
        ...

