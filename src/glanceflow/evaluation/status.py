from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


STATUS_SCHEMA_VERSION = 1
README_START = "<!-- glanceflow-project-status:start -->"
README_END = "<!-- glanceflow-project-status:end -->"

LOCK_PATH = Path("evaluation/real_data/public_web/evaluation_set.lock.json")
PUBLIC_RESULTS_PATH = Path("outputs/evaluation/public_web/public_web_results.json")
STAGE8_STATUS_PATH = Path("outputs/evaluation/stage8_status.json")
PROJECT_STATUS_PATH = Path("project_status.json")
REAL_MANIFEST_PATH = Path("evaluation/real_data/manifest.csv")
USER_STUDY_STATUS_PATH = Path("evaluation/reports/user-study-status.json")
README_PATH = Path("README.md")
PUBLIC_CANDIDATES_PATH = Path("evaluation/real_data/public_web/public_web_candidates.csv")
PUBLIC_MANIFEST_PATH = Path("evaluation/real_data/public_web/manifest.csv")

_LOCK_INPUTS = {
    "source_manifest_hash": Path("evaluation/real_data/public_web/manifest.csv"),
    "sanitized_manifest_hash": Path("evaluation/real_data/public_web/sanitized_manifest.csv"),
    "manual_review_manifest_hash": Path("evaluation/real_data/public_web/manual_review_checklist.csv"),
}
_ANNOTATIONS = Path("evaluation/real_data/public_web/annotations")
_TEST_RESULT_RE = re.compile(r"\b\d+\s+passed(?:\s+in\s+[0-9.]+s)?\b", re.IGNORECASE)


class StatusConsistencyError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StatusConsistencyError(f"Cannot read status source {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StatusConsistencyError(f"Status source must be a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _annotation_hash(root: Path) -> str:
    paths = sorted((root / _ANNOTATIONS).glob("PW-*.json"))
    if not paths:
        raise StatusConsistencyError("No PUBLIC_WEB annotation files were found")
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _validate_lock(root: Path, lock: dict[str, Any]) -> None:
    if lock.get("status") != "READY":
        raise StatusConsistencyError("PUBLIC_WEB lock status is not READY")
    sample_ids = lock.get("sample_ids")
    if not isinstance(sample_ids, list) or not sample_ids:
        raise StatusConsistencyError("PUBLIC_WEB lock has no sample_ids")
    if lock.get("sample_count") != len(sample_ids):
        raise StatusConsistencyError("PUBLIC_WEB lock sample_count does not match sample_ids")

    mismatches = [
        field
        for field, relative in _LOCK_INPUTS.items()
        if lock.get(field) != _sha256(root / relative)
    ]
    if lock.get("annotation_manifest_hash") != _annotation_hash(root):
        mismatches.append("annotation_manifest_hash")
    if mismatches:
        raise StatusConsistencyError(
            "PUBLIC_WEB lock is stale: " + ", ".join(sorted(mismatches))
        )


def _real_sample_count(root: Path) -> int:
    lines = (root / REAL_MANIFEST_PATH).read_text(encoding="utf-8").splitlines()
    return max(len([line for line in lines if line.strip()]) - 1, 0)


def _csv_row_count(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def build_project_status(root: Path) -> dict[str, Any]:
    root = Path(root)
    lock = _read_json(root / LOCK_PATH)
    results = _read_json(root / PUBLIC_RESULTS_PATH)
    user_study = _read_json(root / USER_STUDY_STATUS_PATH)
    _validate_lock(root, lock)

    summary = results.get("summary")
    if not isinstance(summary, dict):
        raise StatusConsistencyError("PUBLIC_WEB results have no summary object")
    result_ids = results.get("lock_sample_ids")
    if result_ids != lock["sample_ids"]:
        raise StatusConsistencyError("PUBLIC_WEB result sample IDs differ from the lock")
    if summary.get("sample_count") != lock["sample_count"]:
        raise StatusConsistencyError("PUBLIC_WEB result sample count differs from the lock")
    if summary.get("status") != "EXECUTED":
        raise StatusConsistencyError("Latest formal PUBLIC_WEB result is not EXECUTED")

    blocked_items = lock.get("blocked_items")
    if not isinstance(blocked_items, dict):
        raise StatusConsistencyError("PUBLIC_WEB lock blocked_items must be an object")
    selected = results.get("selected_sample_count")
    if selected != lock["sample_count"] + len(blocked_items):
        raise StatusConsistencyError("Selected PUBLIC_WEB sample count is inconsistent")
    if results.get("candidate_count") != _csv_row_count(root / PUBLIC_CANDIDATES_PATH):
        raise StatusConsistencyError("PUBLIC_WEB candidate count differs from the candidate manifest")
    if selected != _csv_row_count(root / PUBLIC_MANIFEST_PATH):
        raise StatusConsistencyError("PUBLIC_WEB selected count differs from the source manifest")

    real_count = _real_sample_count(root)
    participants = user_study.get("participants_recruited")
    sessions = user_study.get("sessions_completed")
    if not isinstance(participants, int) or not isinstance(sessions, int):
        raise StatusConsistencyError("User-study counts must be integers")

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "status_sources": {
            "public_web_lock": LOCK_PATH.as_posix(),
            "public_web_results": PUBLIC_RESULTS_PATH.as_posix(),
            "public_web_candidates": PUBLIC_CANDIDATES_PATH.as_posix(),
            "public_web_manifest": PUBLIC_MANIFEST_PATH.as_posix(),
            "real_data_manifest": REAL_MANIFEST_PATH.as_posix(),
            "user_study_status": USER_STUDY_STATUS_PATH.as_posix(),
        },
        "public_web": {
            "dataset": results.get("dataset"),
            "source_type": results.get("source_type"),
            "lock_status": lock["status"],
            "formal_evaluation_status": summary["status"],
            "candidates_audited": results.get("candidate_count"),
            "metadata_selected": selected,
            "samples_evaluated": lock["sample_count"],
            "samples_excluded": len(blocked_items),
            "included_sample_ids": lock["sample_ids"],
            "excluded_sample_ids": sorted(blocked_items),
            "outcome_counts": summary.get("outcome_counts"),
            "metrics": summary.get("metrics"),
        },
        "real_campus_data": {
            "status": "NOT_EXECUTED" if real_count == 0 else "RECORDED",
            "sample_count": real_count,
        },
        "human_user_study": {
            "status": "NOT_EXECUTED" if sessions == 0 else "RECORDED",
            "participants_recruited": participants,
            "sessions_completed": sessions,
            "results_available": bool(user_study.get("results_available")),
        },
        "verification": {
            "current_full_test_result": None,
            "policy": (
                "Current test counts are reported per verified run and are not inferred "
                "from historical handoff or status files."
            ),
        },
    }


def build_stage8_status(project_status: dict[str, Any]) -> dict[str, Any]:
    public = project_status["public_web"]
    real = project_status["real_campus_data"]
    study = project_status["human_user_study"]
    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "generated_from": PROJECT_STATUS_PATH.as_posix(),
        "infrastructure_status": "Stage 8 infrastructure complete",
        "real_data_status": real["status"],
        "user_study_status": study["status"],
        "real_sample_count": real["sample_count"],
        "public_web_status": public["formal_evaluation_status"],
        "public_web_candidates_audited": public["candidates_audited"],
        "public_web_metadata_selected": public["metadata_selected"],
        "public_web_samples_evaluated": public["samples_evaluated"],
        "public_web_samples_excluded": public["samples_excluded"],
        "participant_count": study["participants_recruited"],
        "agent_core_modified": False,
        "current_full_test_result": None,
    }


def render_readme_status(project_status: dict[str, Any]) -> str:
    public = project_status["public_web"]
    metrics = public["metrics"]
    outcomes = public["outcome_counts"]
    real = project_status["real_campus_data"]
    study = project_status["human_user_study"]
    lines = [
        README_START,
        "## 当前项目状态（机器生成）",
        "",
        "本状态块由 `project_status.json` 生成；锁文件和正式评测结果优先于历史交接记录。",
        "",
        f"- PUBLIC_WEB lock：`{public['lock_status']}`",
        f"- PUBLIC_WEB 正式评测：`{public['formal_evaluation_status']}`，"
        f"纳入 {public['samples_evaluated']}，排除 {public['samples_excluded']}",
        f"- OCR usable：{metrics['ocr_usable_rate']['display']}",
        f"- Full-field correct：{metrics['full_field_correct_rate']['display']}",
        f"- SAFE_DEFERRED：{outcomes['SAFE_DEFERRED']}；"
        f"SAFE_BLOCKED：{outcomes['SAFE_BLOCKED']}；"
        f"WRONG_EXECUTION：{outcomes['WRONG_EXECUTION']}",
        f"- 真实校园数据：`{real['status']}`，样本 {real['sample_count']}",
        f"- 真人用户实验：`{study['status']}`，参与者 {study['participants_recruited']}",
        "- 当前全量测试次数：不写入状态汇总；仅以本次实际测试输出单独报告。",
        "- 状态检查：`python scripts/check_status_consistency.py`",
        "",
        "PUBLIC_WEB 只能称为 **Public-Web Real-World Notification Set**，不是校园实拍或真人实验。",
        README_END,
    ]
    return "\n".join(lines)


def _replace_or_insert_readme_block(readme: str, block: str) -> str:
    if README_START in readme or README_END in readme:
        if readme.count(README_START) != 1 or readme.count(README_END) != 1:
            raise StatusConsistencyError("README status markers are malformed")
        start = readme.index(README_START)
        end = readme.index(README_END, start) + len(README_END)
        return readme[:start] + block + readme[end:]
    anchor = "## Stage 8 真实验证入口"
    if anchor not in readme:
        raise StatusConsistencyError(f"README insertion anchor is missing: {anchor}")
    return readme.replace(anchor, block + "\n\n" + anchor, 1)


def expected_readme(root: Path, project_status: dict[str, Any]) -> str:
    readme = (Path(root) / README_PATH).read_text(encoding="utf-8")
    return _replace_or_insert_readme_block(readme, render_readme_status(project_status))


def check_status_consistency(root: Path) -> list[str]:
    root = Path(root)
    issues: list[str] = []
    try:
        expected_project = build_project_status(root)
    except StatusConsistencyError as exc:
        return [str(exc)]

    project_path = root / PROJECT_STATUS_PATH
    if not project_path.exists():
        issues.append(f"Missing generated status: {PROJECT_STATUS_PATH.as_posix()}")
    else:
        try:
            if _read_json(project_path) != expected_project:
                issues.append("project_status.json differs from its formal sources")
        except StatusConsistencyError as exc:
            issues.append(str(exc))

    expected_stage8 = build_stage8_status(expected_project)
    try:
        stage8 = _read_json(root / STAGE8_STATUS_PATH)
        if stage8 != expected_stage8:
            issues.append("outputs/evaluation/stage8_status.json is stale")
        if _TEST_RESULT_RE.search(json.dumps(stage8, ensure_ascii=False)):
            issues.append("stage8_status.json presents a historical test result as current")
    except StatusConsistencyError as exc:
        issues.append(str(exc))

    readme_path = root / README_PATH
    readme = readme_path.read_text(encoding="utf-8")
    expected_block = render_readme_status(expected_project)
    if README_START not in readme or README_END not in readme:
        issues.append("README generated status block is missing")
    else:
        start = readme.index(README_START)
        end = readme.index(README_END, start) + len(README_END)
        if readme[start:end] != expected_block:
            issues.append("README generated status block differs from formal sources")
    if _TEST_RESULT_RE.search(readme):
        issues.append("README presents a test count as current status without run evidence")
    if (
        expected_project["public_web"]["formal_evaluation_status"] == "EXECUTED"
        and "NOT_EXECUTED_LOCAL_CACHE_UNAVAILABLE" in readme
    ):
        issues.append("README contradicts the executed PUBLIC_WEB formal result")
    return issues


def write_generated_status(root: Path) -> list[Path]:
    root = Path(root)
    project = build_project_status(root)
    stage8 = build_stage8_status(project)
    readme_path = root / README_PATH
    readme = readme_path.read_text(encoding="utf-8")
    updated_readme = _replace_or_insert_readme_block(readme, render_readme_status(project))

    outputs = {
        root / PROJECT_STATUS_PATH: json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        root / STAGE8_STATUS_PATH: json.dumps(stage8, ensure_ascii=False, indent=2) + "\n",
        readme_path: updated_readme,
    }
    changed: list[Path] = []
    for path, content in outputs.items():
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8", newline="\n")
            changed.append(path.relative_to(root))
    return changed
