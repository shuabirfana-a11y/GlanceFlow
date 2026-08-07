# PaddleOCR candidate VisionAdapter analysis

- Repository: `PaddlePaddle/PaddleOCR`; reviewed commit `2661c7c0ef5c613e8f93c6e93b2e052399f0f854`.
- License: Apache-2.0; commercial use is permitted with license/notice obligations. Status: **REUSABLE_WITH_ATTRIBUTION**.
- Stack: Python/PaddlePaddle/PaddleX pipelines plus deployment examples for Android and other runtimes.

The current public entry is `paddleocr/_pipelines/ocr.py:PaddleOCR`. Its `predict`/`predict_iter` surfaces detection and recognition configuration, document-orientation processing, score thresholds, device selection, CPU threads, and optional word boxes. Model wrappers are in `paddleocr/_models`; CLI/device normalization is in `_common_args.py`. The Android example is under `deploy/android_demo`.

## Proposed neutral contract

```python
class VisionAdapter(Protocol):
    def recognize(self, image: bytes): ...
    def healthcheck(self) -> bool: ...
    def get_version(self) -> str: ...
    def get_capabilities(self) -> set[str]: ...
```

`RapidOCRAdapter` should wrap the existing provider without behavior changes. A future optional `PaddleOCRAdapter` should translate Paddle results into the existing OCR line/bbox/confidence schema. It must not become a second evidence model.

## Benchmark plan (not executed in Stage 11)

Use the same licensed/synthetic image manifest and cold/warm CPU runs. Measure Chinese poster character/field accuracy, rotated pages, small text, multiple regions, bbox and confidence preservation, median/P90 latency, peak process memory, wheel/model download size, and Windows installation steps. Paddle offers orientation and richer pipeline options but has substantially higher runtime/model complexity. RapidOCR remains production default until reproducible evidence justifies an opt-in change. No Paddle dependency was installed in this stage.

Camera, voice, HUD and phone transport are outside PaddleOCR. Agent calls remain downstream of the existing Safety Gate.
