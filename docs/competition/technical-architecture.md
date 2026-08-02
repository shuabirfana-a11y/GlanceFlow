# 技术架构

```text
明确语音触发
  → 第一视角短时采集
  → 固定间隔抽帧与自动选帧
  → 本地 OCR 证据链
  → 结构化通知草案
  → Safety Gate 四状态决策
  → Action Preflight｜行动预检（重复与冲突检查）
  → HUD 结构化确认
  → 原子事务执行
  → event_id 回读验证
  → 补偿回滚与精准撤销
```

## 信任边界

图像、OCR 和抽取只负责提出草案，不能直接写入日历。`GlanceFlowSessionService` 只持有 `TrustedSchedulingService`，模拟器交互层不直接访问 `CalendarPort`。日历层再通过厂商无关端口连接内存实现或受限 Google 适配器。

安全门执行 15 条确定性规则并返回 `READY_TO_CONFIRM`、`NEED_USER_INPUT`、`RECAPTURE_REQUIRED`、`CONTRADICTION_BLOCKED`。移动或姿态未知时，即使草案已生成也禁止日历写入与撤销。

## 评测架构

Baseline A、Baseline B 与 Full System 使用同一清单、同一输入文件和同一 OCR 观测。七项消融只存在于评测适配层。所有写入都指向隔离内存日历，故障由可追溯的 `MemoryFaultPlan` 注入。
