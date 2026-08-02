# Existing Pipeline 与 Optimized Agent 对比

> 相同的 20 个本地合成/故障注入输入；这是编排层专项测试，不是真实用户、真实校园、实体眼镜或真实 Google Calendar 统计。

| 版本 | 目标完成 | 不安全工具调用 | 故障恢复 |
|---|---:|---:|---:|
| Existing Pipeline | 13/20 | 1 | 2/5 |
| Optimized Agent | 17/20 | 0 | 4/5 |

旧流程与 Agent 使用同一组本地场景配置和故障端口，并保留当前安全门、确认、事务自动回滚与撤销语义；差异来自 Agent 新增的最小澄清、OCR 有限重试和超时幂等回读。