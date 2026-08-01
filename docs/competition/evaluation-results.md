# 初赛评测结果

> 本报告由统一评测脚本从真实程序运行结果自动生成。环境为 Windows 本地 CPU 模拟器，不是实体眼镜延迟，也未访问真实 Google Calendar。

## 数据集

共 46 个固定种子人工构造案例；不含团队实拍素材。类别构成：

- ambiguous_time_expression: 4
- duplicate_or_conflict: 4
- event_with_deadline: 8
- expired_event: 3
- invalid_deadline_order: 2
- low_quality: 4
- missing_location: 3
- multiple_time_ambiguity: 2
- normal_executable: 10
- provider_fault: 2
- weekday_contradiction: 4

## 三系统同集对比

| 系统 | 错误执行率 | 有效覆盖率 | 误拒率 | 日程包完全正确率 | Macro F1 |
|---|---:|---:|---:|---:|---:|
| baseline_a_regex_direct | 58.33% | 75.00% | 25.00% | 75.00% | 0.396 |
| baseline_b_extractor_no_safety | 57.14% | 75.00% | 25.00% | 75.00% | 0.676 |
| full_system | 0.00% | 75.00% | 25.00% | 75.00% | 0.914 |

错误执行率以实际执行数为分母；若系统全部拒绝则显示 N/A，而有效覆盖率为 0%，不会因拒绝一切获得虚假高分。日程包完全正确率以应执行通知为分母，要求标题、时间、地点、可选截止事项及最终活动事件全部正确。

Full System 的 5 个误拒/未完整执行案例中，3 个是应执行通知因证据置信度触发重拍，2 个是提供器故障注入后安全回滚。前者说明当前阈值仍需真实数据标定，后者说明覆盖率没有隐藏事务失败。

两个基线不是故意削弱的占位实现：它们使用同一候选帧和 OCR 观测；Baseline A 运行简单标签/日期正则并直接写入，Baseline B 运行正式抽取器并模拟确认，只移除题设指定的安全和事务保护。

## 七项消融

| 消融 | 错误执行率 | 有效覆盖率 | 误拒率 | 完全正确率 | 失败案例数 |
|---|---:|---:|---:|---:|---:|
| no_image_quality_gate | 6.25% | 75.00% | 25.00% | 75.00% | 6 |
| no_evidence_confidence_rule | 21.05% | 75.00% | 25.00% | 75.00% | 6 |
| no_weekday_consistency | 21.05% | 75.00% | 25.00% | 75.00% | 9 |
| no_duplicate_detection | 11.76% | 75.00% | 25.00% | 75.00% | 7 |
| no_conflict_preflight | 11.76% | 75.00% | 25.00% | 75.00% | 7 |
| no_readback_verification | 6.25% | 75.00% | 25.00% | 75.00% | 5 |
| no_atomic_rollback | 11.76% | 75.00% | 25.00% | 75.00% | 5 |

## 执行可靠性

- readback_consistency_rate: 93.75% (15/16)
- rollback_success_rate: 100.00% (2/2)
- undo_success_rate: 100.00% (1/1)
- duplicate_interception_rate: 100.00% (2/2)
- conflict_detection_rate: 100.00% (2/2)
- idempotency_success_rate: 100.00% (1/1)

## 本地端到端耗时

Full System：平均 1170.8 ms，中位 622.1 ms，P90 2160.8 ms，最小 465.5 ms，最大 5198.9 ms。视频选帧中的多帧 OCR 计入选帧耗时。

## 失败案例

自动选取 10 个可追溯代表案例，覆盖 OCR 错字、时间角色、星期矛盾、模糊画面、多时间、地点缺失、重复、冲突、回读异常和事务回滚。详见 `failure_cases.json`。

## 用户体验测试状态

尚未实际招募参与者，状态为 **待执行**。仓库只提供协议、问卷和空白记录模板，不包含虚构人数、评分或结论。

## 解释边界

数据以人工构造素材为主，样本量只能支持工程回归和初赛展示，不支持总体显著性推断。自然语言时间覆盖有限，未部署真实眼镜，真实 Google Calendar 端到端验证也尚未完成。

## 图表

七张图表位于 `outputs/evaluation/figures/`，全部由本次运行结果生成。
