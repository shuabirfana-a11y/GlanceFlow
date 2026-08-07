# Final three-minute demo script

## 0:00–0:20 — 痛点与一句话

“看见通知”到“完成安排”之间存在行动鸿沟：识别错误一旦直接写入日历，就会成为现实副作用。GlanceFlow 是面向校园高价值时限通知的第一视角可信行动 Agent，把视觉信息转化为有证据、可确认、可验证、可恢复的日程行动。

## 0:20–0:55 — GF-DEMO-01 正常创建

展示第一视角通知、HUD 和逐步模式。依次指出 Capture、OCR、Evidence、Safety、Action Preflight、用户确认、Create、Readback 和 Verify。强调 HUD 成功显示不等于用户确认。

## 0:55–1:25 — GF-DEMO-02 活动与截止

展示同一通知中的报名截止和活动开始。Evidence Card 分别绑定 OCR 行，Temporal Semantics 赋予不同角色，可信事务原子创建主活动与截止提醒。

## 1:25–1:55 — Evidence 与时间语义

指出字段值、line ID、bbox、confidence、source frame 和八位 hash。说明系统不是“猜时间”，确认快照与图像证据绑定；证据或时间语义变化会使旧确认失效。

## 1:55–2:20 — GF-DEMO-04 危险输入阻断

日期与星期矛盾。Safety Gate 输出 `CONTRADICTION_BLOCKED`，HUD 告知暂不创建，Memory Calendar 事件数保持 0。

## 2:20–2:45 — GF-DEMO-08 故障回滚

故意注入回读标题不一致。展示 Create → Readback mismatch → Rollback → Verify deletion，最终事件数 0。说明这是隔离内存日历的故障注入，不是真实 Google Calendar 统计。

## 2:45–2:55 — 三系统对比

相同 20 个本地合成/故障注入场景：Direct 错误执行 11/20，Existing Pipeline 1/20，Optimized Agent 0/20。0/20 只说明当前小样本未观察到错误执行，不代表绝对安全。

## 2:55–3:00 — 总结

GlanceFlow 的价值不是更激进地执行，而是在证据不足、语义矛盾或事务异常时知道何时确认、重采、阻断和恢复。
