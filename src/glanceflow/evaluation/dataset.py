from __future__ import annotations

from pathlib import Path

from glanceflow.evaluation.models import DatasetManifest


def load_manifest(path: Path = Path("evaluation/dataset/dataset_manifest.json")) -> DatasetManifest:
    manifest = DatasetManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))
    missing = [str(sample.input_path) for sample in manifest.samples if not Path(sample.input_path).is_file()]
    if missing:
        raise ValueError(f"评测清单引用了不存在的文件：{', '.join(missing[:3])}")
    return manifest
