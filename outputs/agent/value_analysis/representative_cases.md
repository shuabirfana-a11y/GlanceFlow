# 八个代表性场景的三系统对比

全部案例来自同一组本地确定性场景配置与隔离内存日历。

## AG-001｜正常活动

- 输入风险：none
- Direct Execution：目标按当前评测定义完成，最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：目标按当前评测定义完成，最终状态 SUCCESS。
- Optimized Agent：目标按当前评测定义完成，最终状态 SUCCESS。
- 最终新建事件数：Direct=1，Pipeline=1，Agent=1
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-004｜时间模糊后补充

- 输入风险：missing_event_start
- Direct Execution：未完成目标，最终状态 NEED_INPUT。
- Existing Pipeline：未完成目标，最终状态 NEED_INPUT。
- Optimized Agent：目标按当前评测定义完成，最终状态 SUCCESS。
- 最终新建事件数：Direct=0，Pipeline=0，Agent=1
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-006｜日期星期矛盾

- 输入风险：deterministic_time_contradiction
- Direct Execution：产生错误或未验证日历状态（错误时间），最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：在外部写入前安全停止，最终状态 BLOCKED。
- Optimized Agent：在外部写入前安全停止，最终状态 BLOCKED。
- 最终新建事件数：Direct=1，Pipeline=0，Agent=0
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-008｜重复通知

- 输入风险：duplicate_event
- Direct Execution：产生错误或未验证日历状态（重复创建），最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：在外部写入前安全停止，最终状态 BLOCKED。
- Optimized Agent：在外部写入前安全停止，最终状态 BLOCKED。
- 最终新建事件数：Direct=1，Pipeline=0，Agent=0
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-009｜冲突未接受

- 输入风险：calendar_conflict
- Direct Execution：产生错误或未验证日历状态（冲突未确认执行），最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：在外部写入前安全停止，最终状态 WAIT_CONFIRM。
- Optimized Agent：在外部写入前安全停止，最终状态 WAIT_CONFIRM。
- 最终新建事件数：Direct=1，Pipeline=0，Agent=0
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-012｜确认后草稿修改

- 输入风险：draft_changed_after_confirmation
- Direct Execution：产生错误或未验证日历状态（错误地点），最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：在外部写入前安全停止，最终状态 WAIT_CONFIRM。
- Optimized Agent：在外部写入前安全停止，最终状态 WAIT_CONFIRM。
- 最终新建事件数：Direct=1，Pipeline=0，Agent=0
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-015｜创建超时但实际已创建

- 输入风险：unknown_write_outcome
- Direct Execution：产生错误或未验证日历状态（回读异常仍提交），最终状态 TIMEOUT。
- Existing Pipeline：产生错误或未验证日历状态（回读异常仍提交），最终状态 TIMEOUT。
- Optimized Agent：故障发生后恢复成功，最终状态 SUCCESS。
- 最终新建事件数：Direct=1，Pipeline=1，Agent=1
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。

## AG-017｜回读字段不一致

- 输入风险：readback_mismatch
- Direct Execution：产生错误或未验证日历状态（回读异常仍提交），最终状态 CREATED_UNVERIFIED。
- Existing Pipeline：故障发生后恢复成功，最终状态 ROLLED_BACK。
- Optimized Agent：故障发生后恢复成功，最终状态 FAILED。
- 最终新建事件数：Direct=1，Pipeline=0，Agent=0
- 差异原因：Direct 只依据基本字段完整性；固定流水线提供确定性安全门和事务保护；Agent 进一步按观察选择澄清、等待、验证或恢复动作。
