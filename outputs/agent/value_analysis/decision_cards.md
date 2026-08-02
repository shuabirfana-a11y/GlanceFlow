# Decision Cards

卡片只包含公开理由和结构化策略，不包含思维链、完整 OCR 文本、本地路径或凭据。

## AG-001

- 状态 / 风险：`VERIFYING` / `LOW`
- 动作 / 工具：`VERIFY_TRANSACTION` / `verify_calendar_transaction`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.verifying
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-004

- 状态 / 风险：`VERIFYING` / `LOW`
- 动作 / 工具：`VERIFY_TRANSACTION` / `verify_calendar_transaction`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.verifying
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-006

- 状态 / 风险：`VALIDATING` / `CRITICAL`
- 动作 / 工具：`RUN_SAFETY_GATE` / `evaluate_safety`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.validating
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-008

- 状态 / 风险：`PREFLIGHTING` / `CRITICAL`
- 动作 / 工具：`RUN_PREFLIGHT` / `run_action_preflight`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.preflighting
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-009

- 状态 / 风险：`PREFLIGHTING` / `HIGH`
- 动作 / 工具：`RUN_PREFLIGHT` / `run_action_preflight`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.preflighting
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-012

- 状态 / 风险：`PREFLIGHTING` / `LOW`
- 动作 / 工具：`RUN_PREFLIGHT` / `run_action_preflight`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.preflighting
- 公开理由：根据当前状态选择下一项白名单能力。
- 允许副作用：False

## AG-015

- 状态 / 风险：`RECOVERING` / `LOW`
- 动作 / 工具：`VERIFY_TRANSACTION` / `verify_calendar_transaction`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.recovering, timeout_requires_idempotency_check
- 公开理由：写入超时后先按事务标识回读，禁止重复创建。
- 允许副作用：False

## AG-017

- 状态 / 风险：`RECOVERING` / `CRITICAL`
- 动作 / 工具：`ROLLBACK_TRANSACTION` / `rollback_calendar_transaction`
- 证据：agent-eval-line-1, agent-eval-line-2
- 规则：state.recovering, recovery_requires_rollback
- 公开理由：事务部分成功或回读不一致，执行补偿回滚并验证删除。
- 允许副作用：True
