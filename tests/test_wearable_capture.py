from pathlib import Path

from glanceflow.wearable.capture import FileVideoCaptureProvider
from glanceflow.wearable.models import CaptureRequest


def test_file_capture_has_stable_unique_ids_and_deletes_temporary_video(tmp_path):
    source = tmp_path / "temporary.mp4"
    source.write_bytes(Path("data/synthetic_videos/01_clear_notice.mp4").read_bytes())
    provider = FileVideoCaptureProvider()
    request = CaptureRequest(session_id="capture-test", video_path=source, output_dir=tmp_path / "frames")

    result = provider.capture(request)

    assert not source.exists()
    assert result.raw_video_deleted
    assert 1 <= len(result.sampled_frames) <= 7
    assert len({frame.frame_id for frame in result.sampled_frames}) == len(result.sampled_frames)
    assert [frame.timestamp_ms for frame in result.sampled_frames] == sorted(frame.timestamp_ms for frame in result.sampled_frames)


def test_discard_unselected_retains_exactly_one_frame(tmp_path):
    source = Path("data/synthetic_videos/01_clear_notice.mp4")
    provider = FileVideoCaptureProvider()
    result = provider.capture(CaptureRequest(session_id="privacy-test", video_path=source, output_dir=tmp_path, delete_source_after_processing=False))
    selected = result.sampled_frames[1]

    provider.discard_unselected(result, selected.frame_id)

    assert selected.image_path.exists()
    assert sum(frame.image_path.exists() for frame in result.sampled_frames) == 1
    provider.clear_session("privacy-test")
    assert not selected.image_path.exists()
