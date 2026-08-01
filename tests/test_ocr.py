from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import pytest
from pydantic import ValidationError

from glanceflow import config
from glanceflow.domain.models import EvidenceLine
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.ocr.models import OcrResult
from glanceflow.ocr.quality import add_ocr_text_check, inspect_image_quality


class FakeEngine:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = result
        self.error = error

    def __call__(self, _image):
        if self.error:
            raise self.error
        return self.result, [0.01, 0.01, 0.01]


def create_clear_image(path: Path, size=(1200, 700)) -> None:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    for y in range(80, size[1] - 60, 100):
        draw.rectangle((80, y, size[0] - 100, y + 24), fill="black")
    image.save(path)


def test_ocr_unique_line_ids_bbox_and_source(tmp_path):
    path = tmp_path / "通知.png"
    create_clear_image(path)
    raw = [
        [[[10, 10], [110, 10], [110, 40], [10, 40]], "标题", "0.98"],
        [[[10, 60], [210, 60], [210, 90], [10, 90]], "地点：报告厅", "0.96"],
    ]
    result = RapidOcrProvider(FakeEngine(raw)).recognize(path, "frame-中文-001")
    assert result.success is True
    assert [line.line_id for line in result.evidence_lines] == [
        "frame-中文-001-ocr-0001",
        "frame-中文-001-ocr-0002",
    ]
    assert len({line.line_id for line in result.evidence_lines}) == 2
    assert all(line.source_frame_id == "frame-中文-001" for line in result.evidence_lines)
    assert result.evidence_lines[0].bbox == (10.0, 10.0, 110.0, 40.0)


def test_empty_and_invalid_files_do_not_crash(tmp_path):
    empty = tmp_path / "empty.png"
    empty.write_bytes(b"")
    invalid = tmp_path / "invalid.png"
    invalid.write_text("not an image", encoding="utf-8")

    for path in (empty, invalid):
        quality = inspect_image_quality(path)
        ocr = RapidOcrProvider(FakeEngine([])).recognize(path, "frame-invalid")
        assert quality.passed is False
        assert "GF-IMG-DECODE" in {check.check_id for check in quality.checks if not check.passed}
        assert ocr.success is False
        assert ocr.error_message is not None


def test_ocr_no_text_is_rejected(tmp_path):
    path = tmp_path / "blank.png"
    create_clear_image(path)
    quality = inspect_image_quality(path)
    ocr = RapidOcrProvider(FakeEngine([])).recognize(path, "frame-empty-text")
    final_quality = add_ocr_text_check(quality, [line.text for line in ocr.evidence_lines])
    assert ocr.success is True
    assert ocr.evidence_lines == []
    assert final_quality.passed is False
    assert "GF-OCR-HAS-TEXT" in {check.check_id for check in final_quality.checks if not check.passed}


def test_ocr_exception_becomes_failed_result(tmp_path):
    path = tmp_path / "clear.png"
    create_clear_image(path)
    result = RapidOcrProvider(FakeEngine(error=RuntimeError("engine failed"))).recognize(path, "frame-error")
    assert result.success is False
    assert "RuntimeError" in (result.error_message or "")


def test_clear_image_passes_quality_gate(tmp_path):
    path = tmp_path / "clear.png"
    create_clear_image(path)
    result = inspect_image_quality(path)
    assert result.passed is True
    assert all(check.passed for check in result.checks)


def test_low_resolution_is_rejected(tmp_path):
    path = tmp_path / "small.png"
    create_clear_image(path, size=(320, 240))
    result = inspect_image_quality(path)
    assert result.passed is False
    assert "GF-IMG-RESOLUTION" in {check.check_id for check in result.checks if not check.passed}


def test_blurred_image_is_rejected(tmp_path):
    clear = tmp_path / "source.png"
    blurred = tmp_path / "blurred.png"
    create_clear_image(clear)
    with Image.open(clear) as image:
        image.filter(ImageFilter.GaussianBlur(radius=16)).save(blurred)
    result = inspect_image_quality(blurred)
    assert result.passed is False
    assert "GF-IMG-SHARPNESS" in {check.check_id for check in result.checks if not check.passed}


def test_all_black_image_is_rejected(tmp_path):
    path = tmp_path / "black.png"
    Image.new("RGB", (1200, 700), "black").save(path)
    result = inspect_image_quality(path)
    assert result.passed is False
    assert "GF-IMG-NOT-BLACK" in {check.check_id for check in result.checks if not check.passed}


def test_quality_thresholds_are_centralized():
    assert config.QUALITY_MIN_IMAGE_WIDTH == 640
    assert config.QUALITY_MIN_IMAGE_HEIGHT == 400
    assert config.QUALITY_MIN_LAPLACIAN_VARIANCE == 80.0


@pytest.mark.parametrize("problem", ["duplicate", "source", "bounds", "missing_bbox"])
def test_ocr_result_rejects_invalid_evidence_invariants(problem):
    first = EvidenceLine(
        line_id="line-1",
        text="标题",
        confidence=0.9,
        source_frame_id="frame-1",
        bbox=(10, 10, 100, 40),
    )
    second = EvidenceLine(
        line_id="line-2",
        text="地点",
        confidence=0.9,
        source_frame_id="frame-1",
        bbox=(10, 50, 100, 80),
    )
    if problem == "duplicate":
        second.line_id = "line-1"
    elif problem == "source":
        second.source_frame_id = "frame-other"
    elif problem == "bounds":
        second.bbox = (10, 50, 500, 80)
    else:
        second.bbox = None
    with pytest.raises(ValidationError):
        OcrResult(
            source_frame_id="frame-1",
            image_path=Path("image.png"),
            image_width=200,
            image_height=100,
            evidence_lines=[first, second],
            provider_name="test",
            provider_version="1",
            processing_time_ms=1,
            success=True,
        )
