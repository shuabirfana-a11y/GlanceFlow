from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from glanceflow.domain.models import NoticePackageDraft
from glanceflow.config import DEFAULT_TIMEZONE, SUPPORTED_IMAGE_EXTENSIONS
from glanceflow.ocr.provider import RapidOcrProvider
from glanceflow.pipeline import ImagePipelineResult, process_image
from glanceflow.application.demo import run_calendar_demo
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


def build_image_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GlanceFlow Stage 2 OCR证据链演示")
    parser.add_argument("command", choices=["extract-image"])
    parser.add_argument("input", type=Path, help="单张通知图片或图片目录")
    parser.add_argument("--captured-at", help="带时区的ISO 8601采集时间；默认使用当前时间")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE, help="IANA时区名称")
    return parser


def _display_image_result(result: ImagePipelineResult) -> None:
    print("=" * 72)
    print(f"图片：{result.image_path}")
    print("图像质量结果：")
    for check in result.quality_result.checks:
        marker = "PASS" if check.passed else "FAIL"
        detail = f"；测量值={check.measured_value}；阈值={check.threshold}" if check.measured_value is not None else ""
        print(f"  [{marker}] {check.check_id} {check.message}{detail}")

    if result.ocr_result is None:
        print("OCR文本行：未执行（图像质量门未通过）")
    elif not result.ocr_result.success:
        print(f"OCR文本行：识别失败：{result.ocr_result.error_message}")
    else:
        print(
            f"OCR文本行：provider={result.ocr_result.provider_name} "
            f"version={result.ocr_result.provider_version} "
            f"耗时={result.ocr_result.processing_time_ms:.1f}ms"
        )
        for line in result.ocr_result.evidence_lines:
            print(f"  {line.line_id} conf={line.confidence:.3f} bbox={list(line.bbox or [])} text={line.text}")

    extraction = result.extraction_result
    if extraction is None:
        print("结构化草案：未生成")
    elif extraction.draft is None:
        print("结构化草案：生成失败")
        for issue in extraction.issues:
            print(f"  {issue.issue_id}: {issue.message} evidence={issue.evidence_line_ids}")
    else:
        draft = extraction.draft
        print("结构化草案：")
        print(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2))
        print("字段证据绑定：")
        bindings = {
            "title": draft.main_event.title_evidence.evidence_line_ids,
            "event_start": draft.main_event.time_evidence.evidence_line_ids,
            "location": draft.main_event.location_evidence.evidence_line_ids,
        }
        if draft.deadline_action:
            bindings["deadline"] = draft.deadline_action.deadline_evidence.evidence_line_ids
            bindings["deadline_action"] = draft.deadline_action.action_evidence.evidence_line_ids
        for field, line_ids in bindings.items():
            print(f"  {field}: {line_ids}")

    if result.safety_decision is None:
        print("安全门规则：未执行（质量门或结构化抽取未产生合法草案）")
    else:
        print("安全门规则：")
        for rule in result.safety_decision.rule_results:
            marker = "PASS" if rule.passed else "FAIL"
            print(f"  [{marker}] {rule.rule_id} [{rule.severity.value}] {rule.message}")
    print(f"最终安全状态：{result.final_status.value}")
    print(f"是否允许确认：{'是' if result.can_proceed_to_confirmation else '否'}")
    _show_list("原因", result.reasons)


def _parse_captured_at(value: str | None, timezone: str) -> datetime:
    if value is None:
        return datetime.now(ZoneInfo(timezone))
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--captured-at 必须包含时区。")
    return parsed


def image_main(argv: list[str]) -> int:
    args = build_image_parser().parse_args(argv)
    input_path: Path = args.input
    if not input_path.exists():
        print(f"错误：路径不存在：{input_path}", file=sys.stderr)
        return 2
    try:
        captured_at = _parse_captured_at(args.captured_at, args.timezone)
        ZoneInfo(args.timezone)
    except (ValueError, KeyError) as exc:
        print(f"错误：无效时间参数：{exc}", file=sys.stderr)
        return 2

    if input_path.is_dir():
        paths = sorted(path for path in input_path.iterdir() if path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS)
    else:
        paths = [input_path]
    if not paths:
        print(f"错误：未找到受支持的图片：{input_path}", file=sys.stderr)
        return 2

    provider = RapidOcrProvider()
    existing: list[NoticePackageDraft] = []
    output: list[dict] = []
    for path in paths:
        result = process_image(
            path,
            captured_at,
            args.timezone,
            provider=provider,
            existing_drafts=existing,
        )
        _display_image_result(result)
        output.append({"source_file": str(path), "result": result.model_dump(mode="json")})
        if result.extraction_result and result.extraction_result.draft:
            existing.append(result.extraction_result.draft)

    if input_path.is_dir():
        output_path = Path("outputs") / "stage2_results.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print("=" * 72)
        print(f"批量结果已保存：{output_path}")
    return 0


def calendar_demo_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="GlanceFlow Stage 3可信日历事务演示")
    parser.add_argument("command", choices=["calendar-demo"])
    parser.add_argument(
        "--stage2-results",
        type=Path,
        default=Path("outputs") / "stage2_results.json",
        help="Stage 2批量结果JSON",
    )
    args = parser.parse_args(argv)
    if not args.stage2_results.is_file():
        print(f"错误：Stage 2结果不存在：{args.stage2_results}", file=sys.stderr)
        return 2
    try:
        result = run_calendar_demo(args.stage2_results)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"错误：日历演示失败：{exc}", file=sys.stderr)
        return 2
    output_path = Path("outputs") / "stage3_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("可信日历事务演示：")
    for name, scenario in result["scenarios"].items():
        transaction = scenario.get("undone_transaction") or scenario["transaction"]
        print(f"  {name}: {transaction['status']}")
        print(f"    final_event_ids={scenario['final_event_ids']}")
        if scenario.get("confirmation_error"):
            print(f"    confirmation_error={scenario['confirmation_error']}")
        for audit in transaction["audit_events"]:
            print(f"    [{audit['action']}] {audit['message']}")
    print("Google Calendar真实调用：未执行（无专用测试凭据）")
    print(f"结果已保存：{output_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] == "extract-image":
        return image_main(raw_argv)
    if raw_argv and raw_argv[0] == "calendar-demo":
        return calendar_demo_main(raw_argv)
    args = build_parser().parse_args(raw_argv)
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
