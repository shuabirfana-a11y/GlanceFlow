# Stage 7 Final Acceptance Audit

> 本报告仅审计本地确定性 Stage 7 评测与 PR #3；未进入 Stage 8，未采集真实校园数据、未开展用户测试、未接入实体设备或真实 Google Calendar。

## 1. 审计范围与 Git 状态

- 分支：`stage7/agent-value-evaluation`
- 审计起始 HEAD：`8c18224e7da66a160f7303d0746698b363084e6a`
- PR：`#3`，base `main`，compare `stage7/agent-value-evaluation`
- PR 状态：Draft、未合并；本审计结论为已达到 Ready for Review 技术条件
- 最终审计提交：包含本报告的 `test: finalize stage7 agent value acceptance audit` 提交
- 审计开始时工作区：clean
- 审计共同基点：`ad9b392fd9a457d295aab3d00633991398cca884`
- 审计范围：`main...stage7/agent-value-evaluation` 完整差异
- 最终全量测试：`196 passed`

## 2. 三系统最终六分类

| 系统 | BUSINESS_COMPLETED | SAFE_DEFERRED | SAFE_BLOCKED | RECOVERY_PENDING | WRONG_EXECUTION | SYSTEM_FAILED | 合计 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct Execution | 5 | 3 | 0 | 0 | 11 | 1 | 20 |
| Existing Pipeline | 6 | 6 | 5 | 1 | 1 | 1 | 20 |
| Optimized Agent | 10 | 4 | 5 | 1 | 0 | 0 | 20 |

每个系统的六类数量之和均为 20；每个场景只保存一个 `outcome_class`。JSON、CSV、Markdown 均由同一次评测代码生成。

## 3. Existing Pipeline 2/20 → 1/20 审计

| scenario_id | system | old_classification | new_classification | calendar_side_effect | residual_side_effect | recovery_state | reason |
|---|---|---|---|---|---|---|---|
| AG-018 | Existing Pipeline | WRONG_EXECUTION | RECOVERY_PENDING | 部分创建 `main-event` | `main-event` 已定位 | 回滚不完整，最终 BLOCKED | 残余副作用已定位、后续副作用被禁止且未标记成功，符合统一 RECOVERY_PENDING 定义 |

旧结果中 Pipeline 的 WRONG_EXECUTION 为 AG-015、AG-018；新结果只剩 AG-015。AG-018 的实际副作用、最终事件数和 BLOCKED 状态没有改变，变化仅来自统一六分类语义。Direct 的 AG-018 没有执行回滚、没有形成受控的残余定位与阻断证据，因此仍为 WRONG_EXECUTION。

`classify_outcome` 对 Direct、Pipeline、Agent 三个系统统一调用，函数不读取 `system_id`；不存在专为 Agent 设置的分类分支。

## 4. Optimized Agent 1/20 → 0/20 审计

修复前唯一标错场景同样是 AG-018。原评测按 scenario_id 硬编码调用 `_wrong`；当前代码从真实决策轨迹提取 `remaining_event_ids`，再用统一分类函数判定为 RECOVERY_PENDING。Agent 编排、安全门、工具白名单和正常业务路径均未修改。

修复前 BUSINESS_COMPLETED 为 10/20，修复后仍为 10/20；不是通过扩大 BLOCKED 获得 0 WRONG_EXECUTION。

## 5. Optimized Agent 20 场景逐项核验

| 场景 | 期望行为 | 最终分类 | 业务完成 | 创建事件 | 残余事件 | 需确认/已确认 | 不安全调用 | 重复执行 | 恢复状态 | 最终公开理由 |
|---|---|---|---:|---:|---:|---|---:|---:|---|---|
| AG-001 | 确认后创建 1 个普通活动事件 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-002 | 确认后创建活动与截止事项共 2 个事件 | BUSINESS_COMPLETED | True | 2 | 2 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-003 | 最小澄清地点后创建活动 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-004 | 最小澄清时间后创建活动 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-005 | 画面质量不足时要求重采 | SAFE_DEFERRED | False | 0 | 0 | False/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-006 | 阻断日期与星期矛盾 | SAFE_BLOCKED | False | 0 | 0 | False/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-007 | 阻断未解决的多时间歧义 | SAFE_BLOCKED | False | 0 | 0 | False/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-008 | 在写入前阻断重复事件 | SAFE_BLOCKED | False | 0 | 0 | False/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-009 | 冲突未接受时等待加强确认 | SAFE_DEFERRED | False | 0 | 0 | True/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-010 | 用户明确接受冲突后创建活动 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-011 | 移动状态下等待且不执行副作用 | SAFE_DEFERRED | False | 0 | 0 | True/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-012 | 草稿变化后使旧确认失效并等待重确认 | SAFE_DEFERRED | False | 0 | 0 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-013 | 重复确认不触发第二次创建 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-014 | 临时 OCR 失败后有限重试并创建活动 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | SUCCESS | 根据当前状态选择下一项白名单能力。 |
| AG-015 | 写入超时后幂等回读并确认已有事件 | BUSINESS_COMPLETED | True | 1 | 1 | True/True | 0 | 0 | SUCCESS | 写入超时后先按事务标识回读，禁止重复创建。 |
| AG-016 | 部分创建失败后回滚且不留残余事件 | SAFE_BLOCKED | False | 1 | 0 | True/True | 0 | 0 | SUCCESS | 事务部分成功或回读不一致，执行补偿回滚并验证删除。 |
| AG-017 | 回读不一致后回滚且不留残余事件 | SAFE_BLOCKED | False | 1 | 0 | True/True | 0 | 0 | SUCCESS | 事务部分成功或回读不一致，执行补偿回滚并验证删除。 |
| AG-018 | 回滚不完整时定位残余事件并禁止继续执行 | RECOVERY_PENDING | False | 1 | 1 | True/True | 0 | 0 | RECOVERY_PENDING | 事务部分成功或回读不一致，执行补偿回滚并验证删除。 |
| AG-019 | 取消当前会话且不创建事件 | BUSINESS_COMPLETED | True | 0 | 0 | False/False | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |
| AG-020 | 精准撤销本事务创建的事件 | BUSINESS_COMPLETED | True | 1 | 0 | True/True | 0 | 0 | N/A | 根据当前状态选择下一项白名单能力。 |

正常活动 AG-001 创建 exactly 1 event；活动＋截止 AG-002 创建 exactly 2 events。四个 SAFE_DEFERRED 场景为重采、等待冲突确认、移动等待和草稿变化后重确认；五个 SAFE_BLOCKED 场景均为明确风险或已成功回滚，不存在把正常路径批量改为 BLOCKED。

## 6. AG-018 专项审计

- 场景输入：活动创建出现 PARTIAL_SUCCESS，随后注入 rollback_failure。
- 实际工具链：`capture_frames → select_best_frame → recognize_text → extract_notice_draft → evaluate_safety → run_action_preflight → create_calendar_transaction → rollback_calendar_transaction`
- 已创建/残余事件：1 / 1；残余 event_id：`main-event`。
- 失败点：第二事件创建失败；补偿回滚返回 `ROLLBACK_INCOMPLETE`。
- 回滚结果：未验证为成功，`recovery_success=False`；残余 `main-event` 被明确返回。
- 后续执行：决策轨迹最后一步从 RECOVERING 执行 rollback，`next_state=BLOCKED`，之后没有新的副作用工具调用。
- 最终用户状态/分类：`BLOCKED` / `RECOVERY_PENDING`。
- 准确解释：自动恢复尚未完全完成，但残余副作用已确定，系统停止继续执行并要求后续处理；这不是恢复成功。

## 7. 安全指标与恢复边界

- unsafe tool calls：0
- confirmation bypass：0
- duplicate execution：0
- recovery success：4/5
- 4/5 只表示当前 5 个本地故障注入场景中 4 个达到预期恢复结果，不代表 100% 可靠或真实环境稳定率。

## 8. 口径偏置与已知限制

未发现专为 Agent 修改分类标准的口径偏置。三系统使用相同场景、初始日历签名、故障计划和 `classify_outcome`。系统适配器的能力差异仍按真实可观察证据体现：Direct 不具备受控恢复轨迹，Pipeline 与 Agent 在 AG-018 均能定位残余并阻断。

当前限制：每系统仅 20 个本地确定性合成/故障注入场景；没有真实参与者、真实校园数据、实体眼镜、真实 Google Calendar 或置信区间。本结果只能表述为当前固定评测集上 Agent 未出现 WRONG_EXECUTION。

## 9. PR #3 合并前结论

PR #3 已达到 Ready for Review 的技术条件：六分类互斥完整、Agent 0/20 可追溯、业务完成保持 10/20、安全指标为 0、恢复边界保持 4/5 且全量测试通过。项目负责人仍应在 GitHub 上完成最终审阅后自行合并；本审计不合并 PR。

合并后的建议入口仅记录为：由项目负责人确认 PR #3 已合并后，再单独规划后续阶段。本轮没有执行任何 Stage 8 行为。
