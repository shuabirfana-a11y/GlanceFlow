# Final PPT outline（10 pages）

1. **见程 GlanceFlow**：项目名称、第一视角可信行动 Agent 一句话；标注 Windows 本地仿真。
2. **痛点**：“看见通知”与“完成安排”之间的行动鸿沟；感知错误会放大为现实副作用。
3. **为什么不是 OCR + Calendar**：时间角色、冲突、确认、幂等、回读和恢复缺一不可。
4. **系统总架构**：使用 `final-architecture.svg`，只讲一条可信行动主链。
5. **Evidence + Temporal Semantics**：Evidence Card 截图；活动、截止、签到、取消、改期角色。
6. **Risk-aware Agent**：动作选择、工具前置条件、公开 Decision Trace；不展示思维链。
7. **Trusted Transaction**：Create → Readback → Verify → Commit；异常回滚，按 ID 撤销。
8. **实验结果**：相同 20 个本地合成/故障注入场景中 Direct 11/20、Pipeline 1/20、Agent 0/20 错误执行；同时展示目标完成与 4/5 恢复边界。不得称绝对安全。
9. **Demo 截图**：正常 HUD、Evidence、矛盾阻断、冲突和回滚；所有截图来自真实本地 Demo 页面。
10. **限制与下一步**：当前没有 Rokid 真机、真实校园数据、真人用户、Google Calendar 生产验证或真机延迟；下一步是许可数据采集、设备适配和隔离测试日历验证。
