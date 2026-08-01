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

## Stage 2 OCR 证据链（已实现）

Stage 2 增加了 `OcrProvider` 协议和确定性提取适配器，并遵守：

- OCR 适配器只输出原始 `EvidenceLine`，坐标由 OCR 结果维护；
- 语义提取只引用已有 `line_id`，不得生成像素坐标；
- OCR 或提取器不得直接写日历；
- 产出的草案必须由 Pydantic 校验并经过现有 `evaluate_notice`；
- 模糊帧、无效引用和低置信度继续由安全门拒绝。

### 本地 OCR 方案

- `rapidocr-onnxruntime 1.2.3`，Apache-2.0；
- `onnxruntime 1.28.0`，MIT；
- CPU 本地运行，支持中文并返回文本片段、置信度和真实四点框；
- provider 将四点框转换为包含范围 bbox，但不由抽取器生成或修改坐标；
- `OcrResult` 强制 line_id 唯一、来源帧一致、bbox 非空且不越界。

### 图像质量门

集中阈值位于 `config.py`。当前最小尺寸为 640x400，拉普拉斯方差阈值为 80.0；这些是工程初始值，不是实验最优值。检查包括存在性、格式、解码、分辨率、全黑、明显模糊和 OCR 无文本。

### 确定性抽取

抽取器只支持显式标题/地点标签、完整年月日与 24 小时时间、星期，以及“报名截止/申请截止”和显式截止动作。OCR 片段可依据真实 bbox 组合为视觉行，但字段引用仍保存每个原始 line_id。相对时间不补默认时刻，多活动时间直接返回结构化阻断结果。

### 统一管线

`process_image(...)` 顺序执行质量门、OCR、抽取、Pydantic 和原安全门。质量或 OCR 失败返回 `RECAPTURE_REQUIRED`；无法确定具体时间返回结构化 `NEED_USER_INPUT`；多时间歧义返回 `CONTRADICTION_BLOCKED`。只有产生合法草案后才执行 Stage 1 全部规则。

## Stage 3 日历事务接口边界（未实现）

下一阶段应先定义 `CalendarPort`、创建请求/回读快照、幂等键、事务日志和补偿删除结果，使用内存假实现验证原子语义。真实 Google Calendar、OAuth、凭据管理和外部写入需单独授权后再接入。
