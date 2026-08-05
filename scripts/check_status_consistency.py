from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATUS_MODULE = ROOT / "src/glanceflow/evaluation/status.py"
spec = importlib.util.spec_from_file_location("glanceflow_status", STATUS_MODULE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Cannot load status module: {STATUS_MODULE}")
status_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = status_module
spec.loader.exec_module(status_module)

StatusConsistencyError = status_module.StatusConsistencyError
check_status_consistency = status_module.check_status_consistency
write_generated_status = status_module.write_generated_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Check generated GlanceFlow project status")
    parser.add_argument(
        "--write",
        action="store_true",
        help="explicitly regenerate project_status.json, stage8_status.json, and the README block",
    )
    args = parser.parse_args()

    if args.write:
        try:
            changed = write_generated_status(ROOT)
        except StatusConsistencyError as exc:
            print(f"STATUS WRITE BLOCKED: {exc}", file=sys.stderr)
            return 1
        for path in changed:
            print(f"updated {path.as_posix()}")

    issues = check_status_consistency(ROOT)
    if issues:
        print("STATUS CONSISTENCY FAILED", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("STATUS CONSISTENCY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
