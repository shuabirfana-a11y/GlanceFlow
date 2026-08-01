from __future__ import annotations

from pathlib import Path

from glanceflow.evaluation.models import EvaluationAnnotation, SystemResult


def select_failure_cases(
    results: list[SystemResult], annotations: dict[str, EvaluationAnnotation]
) -> list[dict]:
    full = {result.sample_id: result for result in results if result.system_id == "full_system"}
    targets = [
        ("OCR错字与低置信度", lambda sample: sample.expected_failure_reason == "LOW_EVIDENCE_CONFIDENCE"),
        ("时间角色混淆", lambda sample: sample.category == "invalid_deadline_order"),
        ("日期星期矛盾", lambda sample: sample.category == "weekday_contradiction"),
        ("模糊画面", lambda sample: sample.expected_failure_reason == "BLURRED_IMAGE"),
        ("多时间歧义", lambda sample: sample.category == "multiple_time_ambiguity"),
        ("地点缺失", lambda sample: sample.category == "missing_location"),
        ("重复通知", lambda sample: sample.existing_context == "DUPLICATE"),
        ("日程冲突", lambda sample: sample.existing_context == "CONFLICT"),
        ("回读异常", lambda sample: sample.fault_plan == "READBACK_MISMATCH"),
        ("事务回滚", lambda sample: sample.fault_plan == "SECOND_CREATE_FAILURE"),
    ]
    improvements = {
        "OCR错字与低置信度": "在更大规模、经同意的数据上标定质量与置信度阈值；不在本阶段更换 OCR 模型。",
        "时间角色混淆": "扩充截止/签到/入场角色标注，在规则覆盖前继续阻断。",
        "日期星期矛盾": "保持确定性一致性检查，并在 HUD 同时展示原始日期和星期。",
        "模糊画面": "改进采集姿态提示；低质量仍要求重拍。",
        "多时间歧义": "未来增加多场次交互选择；当前不自动猜测。",
        "地点缺失": "允许用户显式补充地点，但不得由模型臆测。",
        "重复通知": "保留通知级与日历级双重重复检查。",
        "日程冲突": "保留二次明确确认，不自动改时间。",
        "回读异常": "保留 event_id 回读；后续真实测试日历验证供应商边界。",
        "事务回滚": "记录并告警补偿失败；当前内存试验已验证成功回滚。",
    }
    selected: list[dict] = []
    used: set[str] = set()
    for label, predicate in targets:
        sample = next((item for item in annotations.values() if item.sample_id not in used and predicate(item)), None)
        if sample is None:
            continue
        result = full[sample.sample_id]
        used.add(sample.sample_id)
        selected.append({
            "case_id": f"FAIL-{len(selected)+1:02d}",
            "sample_id": sample.sample_id,
            "representative_type": label,
            "input_type": sample.media_type.value,
            "input_path": str(sample.input_path),
            "ocr_result": result.ocr_lines,
            "extracted_fields": result.extracted_fields,
            "ground_truth": {
                "notice_type": sample.expected_notice_type.value,
                "title": sample.expected_title,
                "event_start": sample.expected_event_start,
                "location": sample.expected_location,
                "deadline": sample.expected_deadline,
                "safety_status": sample.expected_safety_status.value,
                "is_executable": sample.is_executable,
            },
            "safety_status": result.predicted_safety_status.value,
            "executed": result.executed,
            "error_layer": result.failure_layer,
            "failure_reasons": result.failure_reasons,
            "current_system_handling": _handling(result),
            "outcome_matches_protocol": (
                result.predicted_safety_status == sample.expected_safety_status
                and not result.erroneous_execution
            ),
            "improvement_direction": improvements[label],
            "trace_source": "由本次统一评测入口真实运行产生。",
        })
    if len(selected) < 10:
        raise ValueError("真实评测结果不足以覆盖10类代表性失败案例。")
    return selected


def _handling(result: SystemResult) -> str:
    if result.rollback_attempted:
        return "检测到创建或回读异常，执行补偿回滚。"
    if result.failure_layer == "preflight":
        return "在日历预检阶段停止，未创建新事件。"
    if result.predicted_safety_status.value == "RECAPTURE_REQUIRED":
        return "拒绝执行并要求重新采集。"
    if result.predicted_safety_status.value == "NEED_USER_INPUT":
        return "拒绝执行并要求补充信息。"
    if result.predicted_safety_status.value == "CONTRADICTION_BLOCKED":
        return "安全门阻断，不允许进入确认。"
    return "按评测协议执行并记录结果。"


def evaluation_report_markdown(
    sample_count: int,
    category_counts: dict[str, int],
    system_metrics: list[dict],
    ablation_metrics: list[dict],
    reliability: dict,
    latency_rows: list[dict],
    failure_count: int,
    coverage_analysis: dict[str, int],
) -> str:
    def pct(metric: dict) -> str:
        return metric["display"]

    lines = [
        "# GlanceFlow Stage 5 自动评测报告",
        "",
        "> 本报告由统一评测脚本从真实程序运行结果自动生成。环境为 Windows 本地 CPU 模拟器，不是实体眼镜延迟，也未访问真实 Google Calendar。",
        "",
        "## 数据集",
        "",
        f"共 {sample_count} 个固定种子人工构造案例；不含团队实拍素材。类别构成：",
        "",
    ]
    lines.extend(f"- {name}: {count}" for name, count in category_counts.items())
    lines += ["", "## 三系统同集对比", "", "| 系统 | 错误执行率 | 有效覆盖率 | 误拒率 | 日程包完全正确率 | Macro F1 |", "|---|---:|---:|---:|---:|---:|"]
    for item in system_metrics:
        lines.append(f"| {item['system_id']} | {pct(item['erroneous_execution_rate'])} | {pct(item['valid_coverage_rate'])} | {pct(item['false_rejection_rate'])} | {pct(item['package_complete_accuracy'])} | {item['safety_macro_f1']:.3f} |")
    lines += [
        "",
        "错误执行率以实际执行数为分母；若系统全部拒绝则显示 N/A，而有效覆盖率为 0%，不会因拒绝一切获得虚假高分。日程包完全正确率以应执行通知为分母，要求标题、时间、地点、可选截止事项及最终活动事件全部正确。",
        "",
        f"Full System 的 {coverage_analysis['false_rejections']} 个误拒/未完整执行案例中，{coverage_analysis['confidence_recaptures']} 个是应执行通知因证据置信度触发重拍，{coverage_analysis['provider_faults']} 个是提供器故障注入后安全回滚。前者说明当前阈值仍需真实数据标定，后者说明覆盖率没有隐藏事务失败。",
        "",
        "两个基线不是故意削弱的占位实现：它们使用同一候选帧和 OCR 观测；Baseline A 运行简单标签/日期正则并直接写入，Baseline B 运行正式抽取器并模拟确认，只移除题设指定的安全和事务保护。",
        "",
        "## 七项消融",
        "",
        "| 消融 | 错误执行率 | 有效覆盖率 | 误拒率 | 完全正确率 | 失败案例数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in ablation_metrics:
        lines.append(f"| {item['system_id']} | {pct(item['erroneous_execution_rate'])} | {pct(item['valid_coverage_rate'])} | {pct(item['false_rejection_rate'])} | {pct(item['package_complete_accuracy'])} | {item['failure_case_count']} |")
    lines += ["", "## 执行可靠性", ""]
    for key, value in reliability.items():
        if isinstance(value, dict) and "display" in value:
            lines.append(f"- {key}: {value['display']} ({value['numerator']}/{value['denominator']})")
    full_total = next(row for row in latency_rows if row["system_id"] == "full_system" and row["stage"] == "total_ms")
    lines += [
        "",
        "## 本地端到端耗时",
        "",
        f"Full System：平均 {full_total['mean_ms']:.1f} ms，中位 {full_total['median_ms']:.1f} ms，P90 {full_total['p90_ms']:.1f} ms，最小 {full_total['min_ms']:.1f} ms，最大 {full_total['max_ms']:.1f} ms。视频选帧中的多帧 OCR 计入选帧耗时。",
        "",
        "## 失败案例",
        "",
        f"自动选取 {failure_count} 个可追溯代表案例，覆盖 OCR 错字、时间角色、星期矛盾、模糊画面、多时间、地点缺失、重复、冲突、回读异常和事务回滚。详见 `failure_cases.json`。",
        "",
        "## 用户体验测试状态",
        "",
        "尚未实际招募参与者，状态为 **待执行**。仓库只提供协议、问卷和空白记录模板，不包含虚构人数、评分或结论。",
        "",
        "## 解释边界",
        "",
        "数据以人工构造素材为主，样本量只能支持工程回归和初赛展示，不支持总体显著性推断。自然语言时间覆盖有限，未部署真实眼镜，真实 Google Calendar 端到端验证也尚未完成。",
    ]
    return "\n".join(lines) + "\n"


def final_scorecard_markdown(scorecard: dict) -> str:
    labels = {
        "erroneous_execution_rate":"错误执行率", "valid_coverage_rate":"有效覆盖率",
        "false_rejection_rate":"误拒率", "package_complete_accuracy":"日程包完全正确率",
        "readback_consistency_rate":"回读一致率", "rollback_success_rate":"回滚成功率",
        "undo_success_rate":"撤销成功率", "median_end_to_end_latency_ms":"端到端中位耗时",
        "sample_count":"样本数量",
    }
    lines = ["# GlanceFlow 最终展示摘要", "", "> Windows 本地 CPU 模拟器结果；非实体眼镜、非真实 Google Calendar。", "", "| 指标 | 结果 | 分子/分母 |", "|---|---:|---:|"]
    for key, label in labels.items():
        value = scorecard[key]
        if isinstance(value, dict):
            lines.append(f"| {label} | {value['display']} | {value.get('numerator', 'N/A')}/{value.get('denominator', 'N/A')} |")
        else:
            lines.append(f"| {label} | {value} | — |")
    return "\n".join(lines) + "\n"
