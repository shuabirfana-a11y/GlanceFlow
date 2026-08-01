from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from glanceflow.domain.models import NoticePackageDraft
from glanceflow.safety.gate import evaluate_notice
from glanceflow.safety.results import SafetyGateDecision


def load_draft(path: Path) -> NoticePackageDraft:
    return NoticePackageDraft.model_validate_json(path.read_text(encoding="utf-8"))


def _show_list(label: str, values: list[str]) -> None:
    print(f"{label}：")
    if values:
        for value in values:
            print(f"  - {value}")
    else:
        print("  - 无")


def display(path: Path, draft: NoticePackageDraft, decision: SafetyGateDecision) -> None:
    deadline = draft.deadline_action
    print("=" * 72)
    print(f"文件：{path}")
    print(f"标题：{draft.main_event.title or '（缺失）'}")
    print(f"活动时间：{draft.main_event.event_start.isoformat()}")
    print(f"地点：{draft.main_event.location or '（缺失）'}")
    if deadline is None:
        print("截止事项：无")
    else:
        print(f"截止事项：{deadline.action or '（动作缺失）'} / {deadline.deadline.isoformat()} / {deadline.role.value}")
    print("规则结果：")
    for result in decision.rule_results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"  [{marker}] {result.rule_id} [{result.severity.value}] {result.message}")
    print(f"最终安全状态：{decision.status.value}")
    print(f"是否允许确认：{'是' if decision.can_proceed_to_confirmation else '否'}")
    _show_list("阻断原因", decision.blocking_reasons)
    _show_list("需要补充的信息", decision.required_user_inputs)
    _show_list("需要重新采集的原因", decision.recapture_reasons)


def evaluate_paths(paths: list[Path]) -> list[dict]:
    existing: list[NoticePackageDraft] = []
    output: list[dict] = []
    for path in paths:
        draft = load_draft(path)
        decision = evaluate_notice(draft, existing)
        display(path, draft, decision)
        output.append({"source_file": str(path), "decision": decision.model_dump(mode="json")})
        existing.append(draft)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GlanceFlow Stage 1 行动安全门演示")
    parser.add_argument("input", type=Path, help="单个 JSON 文件或包含 JSON 文件的目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    input_path: Path = args.input
    if not input_path.exists():
        print(f"错误：路径不存在：{input_path}", file=sys.stderr)
        return 2
    paths = sorted(input_path.glob("*.json")) if input_path.is_dir() else [input_path]
    if not paths:
        print(f"错误：未找到 JSON 文件：{input_path}", file=sys.stderr)
        return 2
    try:
        results = evaluate_paths(paths)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"错误：无法读取或校验草案：{exc}", file=sys.stderr)
        return 2

    if input_path.is_dir():
        output_path = Path("outputs") / "stage1_results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("=" * 72)
        print(f"批量结果已保存：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

