from __future__ import annotations

import shutil
from pathlib import Path

import cv2

from glanceflow.wearable.models import CaptureRequest, CaptureResult, SampledFrame


class CaptureError(RuntimeError):
    pass


class FileVideoCaptureProvider:
    """Extracts deterministic frames from only the opening short capture window."""

    def __init__(self) -> None:
        self._session_dirs: dict[str, Path] = {}

    def capture(self, request: CaptureRequest) -> CaptureResult:
        source = Path(request.video_path)
        if not source.is_file():
            raise CaptureError(f"视频不存在：{source}")
        if Path(request.session_id).name != request.session_id:
            raise CaptureError("session_id 不能包含路径。")
        session_dir = (Path(request.output_dir) / request.session_id).resolve()
        session_dir.mkdir(parents=True, exist_ok=True)
        self._session_dirs[request.session_id] = session_dir
        video = cv2.VideoCapture(str(source))
        frames: list[SampledFrame] = []
        deleted = False
        try:
            if not video.isOpened():
                raise CaptureError("无法读取视频。")
            fps = float(video.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = int(video.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if fps <= 0:
                raise CaptureError("视频帧率无效。")
            source_duration_ms = int(round(frame_count / fps * 1000))
            limit = min(source_duration_ms, request.max_capture_ms)
            timestamp = 0
            index = 0
            while timestamp <= limit:
                video.set(cv2.CAP_PROP_POS_MSEC, timestamp)
                ok, frame = video.read()
                if not ok:
                    break
                frame_id = f"{request.session_id}-f{index:03d}-t{timestamp:06d}"
                path = session_dir / f"{frame_id}.png"
                encoded, data = cv2.imencode(".png", frame)
                if not encoded:
                    raise CaptureError("抽帧编码失败。")
                data.tofile(path)
                height, width = frame.shape[:2]
                frames.append(
                    SampledFrame(
                        frame_id=frame_id,
                        timestamp_ms=timestamp,
                        image_path=path,
                        width=width,
                        height=height,
                        file_size_bytes=path.stat().st_size,
                    )
                )
                index += 1
                timestamp += request.sample_interval_ms
        finally:
            video.release()
            if request.delete_source_after_processing:
                source.unlink(missing_ok=True)
                deleted = not source.exists()
        if not frames:
            raise CaptureError("短视频中没有可用帧。")
        warnings = []
        if source_duration_ms > request.max_capture_ms:
            warnings.append("输入较长，仅处理明确触发后的短时窗口。")
        return CaptureResult(
            session_id=request.session_id,
            source_video_name=source.name,
            sampled_frames=frames,
            source_duration_ms=source_duration_ms,
            captured_duration_ms=limit,
            raw_video_deleted=deleted,
            warnings=warnings,
        )

    def discard_unselected(self, result: CaptureResult, selected_frame_id: str | None) -> None:
        for frame in result.sampled_frames:
            if frame.frame_id != selected_frame_id:
                frame.image_path.unlink(missing_ok=True)

    def clear_session(self, session_id: str) -> None:
        tracked = self._session_dirs.pop(session_id, None)
        if tracked and tracked.is_dir():
            shutil.rmtree(tracked)
        safe_id = Path(session_id).name
        for root in (Path("work") / "wearable-captures", Path("work") / "uploads"):
            target = (root / safe_id).resolve()
            root_resolved = root.resolve()
            if target.parent == root_resolved and target.is_dir():
                shutil.rmtree(target)
