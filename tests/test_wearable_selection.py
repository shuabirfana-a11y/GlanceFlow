from pathlib import Path

import cv2

from glanceflow.domain.models import EvidenceLine
from glanceflow.ocr.models import OcrResult
from glanceflow.wearable.frame_selection import DeterministicFrameSelector
from glanceflow.wearable.models import CaptureResult, SampledFrame


class FakeOcr:
    def recognize(self, image_path, source_frame_id):
        image = cv2.imread(str(image_path))
        h, w = image.shape[:2]
        lines = [
            EvidenceLine(line_id=f"{source_frame_id}-1", text="创新创业讲座", confidence=.95, source_frame_id=source_frame_id, bbox=(10, 10, 200, 40)),
            EvidenceLine(line_id=f"{source_frame_id}-2", text="2026年10月18日 14:30", confidence=.94, source_frame_id=source_frame_id, bbox=(10, 50, 300, 80)),
            EvidenceLine(line_id=f"{source_frame_id}-3", text="地点：大学生活动中心", confidence=.96, source_frame_id=source_frame_id, bbox=(10, 90, 300, 120)),
        ]
        return OcrResult(source_frame_id=source_frame_id, image_path=image_path, image_width=w, image_height=h, evidence_lines=lines, provider_name="fake", provider_version="1", processing_time_ms=1, success=True)


def _sample(frame_id, path, timestamp):
    image = cv2.imread(str(path)); h, w = image.shape[:2]
    return SampledFrame(frame_id=frame_id, timestamp_ms=timestamp, image_path=path, width=w, height=h, file_size_bytes=path.stat().st_size)


def test_selector_uses_scores_and_rejects_blur(tmp_path):
    clear = Path("data/synthetic_posters/01_valid_event.png")
    blurred = tmp_path / "blurred.png"
    image = cv2.imread(str(clear)); cv2.imwrite(str(blurred), cv2.GaussianBlur(image, (51, 51), 0))
    capture = CaptureResult(session_id="s", source_video_name="x.mp4", sampled_frames=[_sample("early-blur", blurred, 0), _sample("later-clear", clear, 500)], source_duration_ms=1000, captured_duration_ms=1000, raw_video_deleted=False)

    result = DeterministicFrameSelector(provider=FakeOcr()).select(capture)

    assert result.selected_frame_id == "later-clear"
    assert result.scores[1].total_score > result.scores[0].total_score
    assert set(result.scores[1].component_scores) == set(DeterministicFrameSelector.weights)


def test_selector_requests_recapture_when_all_frames_blur(tmp_path):
    source = cv2.imread("data/synthetic_posters/01_valid_event.png")
    frames = []
    for index in range(2):
        path = tmp_path / f"blur-{index}.png"; cv2.imwrite(str(path), cv2.GaussianBlur(source, (71, 71), 0)); frames.append(_sample(str(index), path, index * 500))
    capture = CaptureResult(session_id="s", source_video_name="x.mp4", sampled_frames=frames, source_duration_ms=1000, captured_duration_ms=1000, raw_video_deleted=False)

    result = DeterministicFrameSelector(provider=FakeOcr()).select(capture)

    assert result.requires_recapture
    assert result.selected_frame_id is None
