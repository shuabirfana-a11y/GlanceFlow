from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.0-Competition"
PACKAGE_NAME = f"GlanceFlow-v{VERSION}"
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", ".pytest_cache", "raw", "private", "work", "temp", "tmp"}
FORBIDDEN_SUFFIXES = {".pem", ".key", ".log", ".tmp", ".temp", ".pyc"}
FORBIDDEN_NAMES = {".env", "credentials.json", "token.json", "client_secret.json"}
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".csv", ".ps1", ".toml", ".html", ".js", ".css", ".svg"}


def _copy_tree(source: Path, target: Path) -> None:
    def ignored(path: str, names: list[str]) -> set[str]:
        return {name for name in names if name in FORBIDDEN_PARTS or name in FORBIDDEN_NAMES or Path(name).suffix.lower() in FORBIDDEN_SUFFIXES}
    shutil.copytree(source, target, ignore=ignored)


def _git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _assert_safe(package: Path) -> None:
    for path in package.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(package)
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or path.name in FORBIDDEN_NAMES or path.suffix.lower() in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"forbidden package path: {relative.as_posix()}")
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "C:\\Users\\" in text or "/home/" in text:
                raise RuntimeError(f"absolute local path in package: {relative.as_posix()}")
            if "-----BEGIN PRIVATE KEY-----" in text:
                raise RuntimeError(f"private key marker in package: {relative.as_posix()}")


def _hashes(package: Path) -> dict[str, str]:
    return {path.relative_to(package).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(package.rglob("*")) if path.is_file() and path.name != "submission_manifest.json"}


def build(output_root: Path = ROOT / "dist") -> tuple[Path, Path]:
    package = output_root / PACKAGE_NAME
    zip_path = output_root / f"{PACKAGE_NAME}.zip"
    if package.exists(): shutil.rmtree(package)
    if zip_path.exists(): zip_path.unlink()
    package.mkdir(parents=True)

    source = package / "source"; source.mkdir()
    _copy_tree(ROOT / "src", source / "src")
    _copy_tree(ROOT / "data", source / "data")
    _copy_tree(ROOT / "demo", source / "demo")
    for name in ("pyproject.toml",): shutil.copy2(ROOT / name, source / name)
    _copy_tree(ROOT / "demo", package / "demo")
    _copy_tree(ROOT / "docs", package / "docs")
    scripts = package / "scripts"; scripts.mkdir()
    for name in ("run_competition_demo.ps1", "reset_competition_demo.ps1", "final_preflight.ps1"):
        shutil.copy2(ROOT / "scripts" / name, scripts / name)
    evaluation = package / "evaluation-summary"; evaluation.mkdir()
    for source_path in (
        ROOT / "docs/competition/final-metrics.md", ROOT / "outputs/evaluation/metric_audit.json",
        ROOT / "outputs/agent/value_analysis/system_comparison.csv", ROOT / "outputs/demo/scenario_results.json",
        ROOT / "outputs/demo/repeatability_results.json", ROOT / "outputs/demo/latency_results.csv",
        ROOT / "outputs/demo/demo_health.json",
    ):
        shutil.copy2(source_path, evaluation / source_path.name)
    shutil.copy2(ROOT / "README.md", package / "README.md")
    shutil.copy2(ROOT / "requirements.txt", package / "requirements.txt")
    shutil.copy2(ROOT / "NOTICE-THIRD-PARTY.md", package / "NOTICE-THIRD-PARTY.md")
    (package / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    (package / "README-START-HERE.md").write_text(
        "# Start here\n\nThis package is a Windows local simulator, not Rokid hardware. From this extracted directory:\n\n"
        "```powershell\nC:\\x\\python.exe -m venv .venv\n.\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
        ".\\.venv\\Scripts\\python.exe -m pip install --editable source\n"
        ".\\.venv\\Scripts\\python.exe -m glanceflow.demo.healthcheck\n"
        ".\\.venv\\Scripts\\python.exe -m glanceflow.demo.run\n"
        ".\\.venv\\Scripts\\python.exe -m glanceflow.simulator.app\n```\n\n"
        "Open http://127.0.0.1:8765 and run GF-DEMO-01 or GF-DEMO-04. The default path is offline and uses MemoryCalendar only.\n",
        encoding="utf-8",
    )
    _assert_safe(package)
    health = json.loads((ROOT / "outputs/demo/demo_health.json").read_text(encoding="utf-8"))
    test_summary_path = ROOT / "outputs/final/test_summary.json"
    tests = json.loads(test_summary_path.read_text(encoding="utf-8")) if test_summary_path.is_file() else {"passed": None, "skipped": None, "failed": None, "status": "NOT_RUN_IN_THIS_CHECKOUT"}
    manifest = {
        "version": VERSION, "git_commit": _git_commit(), "build_time_utc": datetime.now(timezone.utc).isoformat(),
        "tests": tests, "demo_health": health["FINAL"],
        "known_limitations": ["NOT_YET_VALIDATED_ON_ROKID", "REAL_CAMPUS_SAMPLE_COUNT_0", "USER_STUDY_PARTICIPANT_COUNT_0", "NO_REAL_GOOGLE_CALENDAR_VALIDATION", "NO_PHYSICAL_GLASSES_LATENCY"],
        "file_hashes": _hashes(package),
    }
    (package / "submission_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=output_root, base_dir=PACKAGE_NAME)
    return package, zip_path


def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--output-root", type=Path, default=ROOT / "dist")
    args = parser.parse_args(); package, archive = build(args.output_root)
    print(f"PACKAGE={package}"); print(f"ZIP={archive}"); print(f"ZIP_BYTES={archive.stat().st_size}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
