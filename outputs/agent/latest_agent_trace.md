# Agent 决策轨迹示例

该轨迹来自本地确定性场景，不包含自由思维链或敏感信息。

## 1. START_CAPTURE

- 状态：`IDLE` → `SELECTING_FRAME`
- 风险：`LOW`
- 工具：`capture_frames`
- 公开依据：根据当前状态选择下一项白名单能力。

## 2. SELECT_FRAME

- 状态：`SELECTING_FRAME` → `READING`
- 风险：`LOW`
- 工具：`select_best_frame`
- 公开依据：根据当前状态选择下一项白名单能力。

## 3. RUN_OCR

- 状态：`READING` → `READING`
- 风险：`LOW`
- 工具：`recognize_text`
- 公开依据：根据当前状态选择下一项白名单能力。

## 4. RUN_OCR

- 状态：`READING` → `EXTRACTING`
- 风险：`LOW`
- 工具：`recognize_text`
- 公开依据：根据当前状态选择下一项白名单能力。

## 5. EXTRACT_DRAFT

- 状态：`EXTRACTING` → `VALIDATING`
- 风险：`LOW`
- 工具：`extract_notice_draft`
- 公开依据：根据当前状态选择下一项白名单能力。

## 6. RUN_SAFETY_GATE

- 状态：`VALIDATING` → `PREFLIGHTING`
- 风险：`LOW`
- 工具：`evaluate_safety`
- 公开依据：根据当前状态选择下一项白名单能力。

## 7. RUN_PREFLIGHT

- 状态：`PREFLIGHTING` → `WAIT_CONFIRM`
- 风险：`LOW`
- 工具：`run_action_preflight`
- 公开依据：根据当前状态选择下一项白名单能力。

## 8. EXECUTE_TRANSACTION

- 状态：`WAIT_CONFIRM` → `VERIFYING`
- 风险：`LOW`
- 工具：`create_calendar_transaction`
- 公开依据：确认快照与当前草稿、风险和冲突状态一致，可以执行事务。

## 9. VERIFY_TRANSACTION

- 状态：`VERIFYING` → `SUCCESS`
- 风险：`LOW`
- 工具：`verify_calendar_transaction`
- 公开依据：根据当前状态选择下一项白名单能力。
