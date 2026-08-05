from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS_MODULE = ROOT / "src/glanceflow/evaluation/status.py"
spec = importlib.util.spec_from_file_location("glanceflow_status_tests", STATUS_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load status module: {STATUS_MODULE}")
status_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = status_module
spec.loader.exec_module(status_module)

LOCK_PATH = status_module.LOCK_PATH
PROJECT_STATUS_PATH = status_module.PROJECT_STATUS_PATH
PUBLIC_RESULTS_PATH = status_module.PUBLIC_RESULTS_PATH
README_PATH = status_module.README_PATH
STAGE8_STATUS_PATH = status_module.STAGE8_STATUS_PATH
StatusConsistencyError = status_module.StatusConsistencyError
check_status_consistency = status_module.check_status_consistency
write_generated_status = status_module.write_generated_status


def _status_fixture(tmp_path: Path) -> Path:
    paths = [
        LOCK_PATH,
        PUBLIC_RESULTS_PATH,
        Path("evaluation/real_data/manifest.csv"),
        Path("evaluation/reports/user-study-status.json"),
        Path("evaluation/real_data/public_web/manifest.csv"),
        Path("evaluation/real_data/public_web/public_web_candidates.csv"),
        Path("evaluation/real_data/public_web/sanitized_manifest.csv"),
        Path("evaluation/real_data/public_web/manual_review_checklist.csv"),
        README_PATH,
    ]
    paths.extend(
        path.relative_to(ROOT)
        for path in sorted((ROOT / "evaluation/real_data/public_web/annotations").glob("PW-*.json"))
    )
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    write_generated_status(tmp_path)
    return tmp_path


class StatusConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_repository_status_is_consistent(self) -> None:
        self.assertEqual(check_status_consistency(ROOT), [])

    def test_readme_drift_is_detected(self) -> None:
        root = _status_fixture(self.temp_path)
        readme = (root / README_PATH).read_text(encoding="utf-8")
        (root / README_PATH).write_text(
            readme.replace("纳入 9，排除 6", "纳入 10，排除 5"), encoding="utf-8"
        )
        self.assertIn(
            "README generated status block differs from formal sources",
            check_status_consistency(root),
        )

    def test_stale_public_web_readme_claim_is_detected(self) -> None:
        root = _status_fixture(self.temp_path)
        readme = (root / README_PATH).read_text(encoding="utf-8")
        (root / README_PATH).write_text(
            readme + "\nCurrent formal run: NOT_EXECUTED_LOCAL_CACHE_UNAVAILABLE\n",
            encoding="utf-8",
        )
        self.assertIn(
            "README contradicts the executed PUBLIC_WEB formal result",
            check_status_consistency(root),
        )

    def test_stage8_status_drift_is_detected(self) -> None:
        root = _status_fixture(self.temp_path)
        path = root / STAGE8_STATUS_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["public_web_status"] = "NOT_EXECUTED_LOCAL_CACHE_UNAVAILABLE"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertIn(
            "outputs/evaluation/stage8_status.json is stale",
            check_status_consistency(root),
        )

    def test_lock_sample_count_drift_blocks_generation(self) -> None:
        root = _status_fixture(self.temp_path)
        path = root / LOCK_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["sample_count"] = 10
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(StatusConsistencyError, "sample_count"):
            write_generated_status(root)

    def test_candidate_count_drift_blocks_generation(self) -> None:
        root = _status_fixture(self.temp_path)
        path = root / "evaluation/real_data/public_web/public_web_candidates.csv"
        rows = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(StatusConsistencyError, "candidate count"):
            write_generated_status(root)

    def test_historical_test_result_cannot_be_current_status(self) -> None:
        root = _status_fixture(self.temp_path)
        path = root / STAGE8_STATUS_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["full_test_result"] = "244 passed in 1.00s"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertIn(
            "stage8_status.json presents a historical test result as current",
            check_status_consistency(root),
        )

    def test_stale_lock_hash_blocks_generation(self) -> None:
        root = _status_fixture(self.temp_path)
        path = root / "evaluation/real_data/public_web/manifest.csv"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with self.assertRaisesRegex(StatusConsistencyError, "lock is stale"):
            write_generated_status(root)


if __name__ == "__main__":
    unittest.main()
