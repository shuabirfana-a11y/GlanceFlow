from __future__ import annotations

import json
from pathlib import Path

from scripts.build_final_package import PACKAGE_NAME, build
from scripts.generate_final_metrics import generate


def test_final_metrics_are_generated_from_program_outputs(tmp_path):
    text = generate(tmp_path / "metrics.md")
    assert "Direct Execution | 11/20" in text
    assert "Existing Pipeline | 1/20" in text
    assert "Optimized Agent | 0/20" in text
    assert "SIMULATOR REPEATABILITY TEST" in text


def test_final_package_has_required_structure_and_no_forbidden_paths(tmp_path):
    package, archive = build(tmp_path)
    assert package.name == PACKAGE_NAME and archive.is_file()
    required = {"README-START-HERE.md", "README.md", "source", "demo", "docs", "evaluation-summary", "scripts", "requirements.txt", "NOTICE-THIRD-PARTY.md", "VERSION", "submission_manifest.json"}
    assert required <= {path.name for path in package.iterdir()}
    paths = [part for path in package.rglob("*") for part in path.relative_to(package).parts]
    assert not ({".git", ".venv", "__pycache__", ".pytest_cache", "raw", "private"} & set(paths))


def test_submission_manifest_binds_every_packaged_file(tmp_path):
    package, _ = build(tmp_path)
    manifest = json.loads((package / "submission_manifest.json").read_text(encoding="utf-8"))
    actual = {path.relative_to(package).as_posix() for path in package.rglob("*") if path.is_file() and path.name != "submission_manifest.json"}
    assert set(manifest["file_hashes"]) == actual
    assert manifest["demo_health"] == "READY_FOR_COMPETITION_DEMO"
    assert manifest["tests"]["status"] in {"PASS", "FAIL", "NOT_RUN_IN_THIS_CHECKOUT"}


def test_readme_and_final_documents_keep_claim_boundaries():
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "IMPLEMENTED AND SIMULATED" in readme and "NOT YET VALIDATED" in readme
    assert "真实校园采集数据" in readme and "Rokid 实体设备" in readme
    assert Path("docs/competition/final-architecture.svg").is_file()
