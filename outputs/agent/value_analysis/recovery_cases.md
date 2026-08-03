# 故障恢复案例

5 个本地故障注入场景不代表大规模稳定性统计。

- `AG-014`｜Direct Execution｜分类：`SYSTEM_FAILED`｜恢复：False｜最终事件 0 个｜状态 OCR_TEMPORARY
- `AG-015`｜Direct Execution｜分类：`WRONG_EXECUTION`｜恢复：False｜最终事件 1 个｜状态 TIMEOUT
- `AG-016`｜Direct Execution｜分类：`WRONG_EXECUTION`｜恢复：False｜最终事件 1 个｜状态 PARTIAL_SUCCESS
- `AG-017`｜Direct Execution｜分类：`WRONG_EXECUTION`｜恢复：None｜最终事件 1 个｜状态 CREATED_UNVERIFIED
- `AG-018`｜Direct Execution｜分类：`WRONG_EXECUTION`｜恢复：False｜最终事件 1 个｜状态 PARTIAL_SUCCESS
- `AG-014`｜Existing Pipeline｜分类：`SYSTEM_FAILED`｜恢复：None｜最终事件 0 个｜状态 OCR_TEMPORARY
- `AG-015`｜Existing Pipeline｜分类：`WRONG_EXECUTION`｜恢复：False｜最终事件 1 个｜状态 TIMEOUT
- `AG-016`｜Existing Pipeline｜分类：`SAFE_BLOCKED`｜恢复：True｜最终事件 0 个｜状态 ROLLED_BACK
- `AG-017`｜Existing Pipeline｜分类：`SAFE_BLOCKED`｜恢复：True｜最终事件 0 个｜状态 ROLLED_BACK
- `AG-018`｜Existing Pipeline｜分类：`RECOVERY_PENDING`｜恢复：False｜最终事件 1 个｜状态 BLOCKED
- `AG-014`｜Optimized Agent｜分类：`BUSINESS_COMPLETED`｜恢复：True｜最终事件 1 个｜状态 SUCCESS
- `AG-015`｜Optimized Agent｜分类：`BUSINESS_COMPLETED`｜恢复：True｜最终事件 1 个｜状态 SUCCESS
- `AG-016`｜Optimized Agent｜分类：`SAFE_BLOCKED`｜恢复：True｜最终事件 0 个｜状态 FAILED
- `AG-017`｜Optimized Agent｜分类：`SAFE_BLOCKED`｜恢复：True｜最终事件 0 个｜状态 FAILED
- `AG-018`｜Optimized Agent｜分类：`RECOVERY_PENDING`｜恢复：False｜最终事件 1 个｜状态 BLOCKED