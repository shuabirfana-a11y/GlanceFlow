# GlanceFlow Stage 1 Specification

## 目标

把已经提取出的校园线下通知表示为可追溯的 `NoticePackageDraft`，再通过确定性规则判断它是否足以进入用户确认。Stage 1 不执行任何真实日历或其他外部操作。

## 支持范围

当前只支持：

1. 一个线下主活动；
2. 一个可选的前置截止事项；
3. JSON 输入与输出；
4. 基于已评估草案的精确开始时间加标准化标题重复检测。

## 数据契约

- `EvidenceLine` 保存 OCR 行 ID、原文、置信度、源帧和可选坐标；同一草案内 `line_id` 必须唯一。
- `FieldEvidence` 保存字段引用的真实行 ID 和字段置信度。
- `MainEvent` 保存标题、带时区的开始时间、地点、三类核心证据和原始时间文本。
- `DeadlineAction` 保存带时区的截止时间、动作、角色及证据。
- `NoticePackageDraft` 使用 `GF-PKG-0001` 格式 ID，默认时区为 `Asia/Shanghai`。
- 所有模型禁止未声明的额外字段。

Pydantic 输入边界要求 `captured_at`、`event_start` 和 `deadline` 为 aware datetime；安全门的 `GF-TIME-001/002` 仍作为防御性校验保留。

## 规则目录

| 规则 | 失败处理 |
|---|---|
| `GF-FIELD-001/002` | 标题或地点缺失，需要用户补充 |
| `GF-TIME-001/002/003/004` | 时区缺失、过期、日期星期矛盾，阻断 |
| `GF-TIME-005` | 未解析时间表达，需要用户补充 |
| `GF-DEADLINE-001` | 截止事项不完整，需要用户补充 |
| `GF-DEADLINE-002` | 截止不早于活动，阻断 |
| `GF-EVIDENCE-001` | 核心字段未绑定证据，需要用户补充 |
| `GF-EVIDENCE-002/003` | 无效行 ID 或跨帧证据，需要重新采集 |
| `GF-CONFIDENCE-001` | 核心证据低于 0.75，需要重新采集 |
| `GF-NOTICE-001` | 通知类型与字段组合矛盾，阻断 |
| `GF-DUPLICATE-001` | 标准化标题和开始时间相同，阻断 |

统一入口：

```python
evaluate_notice(
    draft: NoticePackageDraft,
    existing_drafts: list[NoticePackageDraft] | None = None,
) -> SafetyGateDecision
```

它执行全部规则、不修改输入，并通过固定优先级生成唯一最终状态。仅 `READY_TO_CONFIRM` 的 `can_proceed_to_confirmation` 为 `true`。

## Stage 2 OCR 接口边界

下一阶段可以增加 `OcrProvider` 协议和提取适配器，但必须遵守：

- OCR 适配器只输出原始 `EvidenceLine`，坐标由 OCR 结果维护；
- 语义提取只引用已有 `line_id`，不得生成像素坐标；
- OCR 或提取器不得直接写日历；
- 产出的草案必须由 Pydantic 校验并经过现有 `evaluate_notice`；
- 模糊帧、无效引用和低置信度继续由安全门拒绝。

