# Stage 4 本地眼镜交互模拟器

Stage 4 只模拟第一视角眼镜工作流，不声称真实设备部署。默认运行在 Windows 本机，使用内存日历。

```text
明确语音触发
  -> 最多3秒短视频采集
  -> 固定间隔抽帧
  -> 可解释的确定性自动选帧
  -> 既有图片质量门 / RapidOCR / 证据抽取 / 安全门
  -> 既有日历预检
  -> 最小 HUD 明确确认
  -> 既有可信事务创建 / event_id回读
  -> 成功提示或安全回滚
  -> 按事务 event_id 精准撤销
```

## 边界

`GlanceFlowSessionService` 是交互编排入口，只依赖 `TrustedSchedulingService`。可穿戴层和浏览器层均不知道 `CalendarPort`，因此不能绕过 Stage 3 的结构化确认、原子创建、回读验证、回滚和撤销约束。

选帧器为每帧记录清晰度、亮度、分辨率、OCR 平均置信度、文本量和关键字段完整度分项，按固定权重计算总分；低于阈值时返回 `RECAPTURE`。分数和原因进入会话审计结果，演示程序不会人工指定最佳帧。

姿态由 `MotionProvider` 提供。当前 `ManualMotionProvider` 是测试/模拟实现。`MOVING` 与 `UNKNOWN` 状态不阻止识别和草案生成，但会把确认与所有日历写操作留在等待态。

## 本地接口

- `POST /api/sessions`：创建内存会话。
- `POST /api/sessions/{id}/capture`：接收单段短视频，并在明确安排指令下处理。
- `POST /api/sessions/{id}/voice`：处理确认、取消、撤销等白名单指令。
- `GET /api/sessions/{id}`：读取会话与 HUD。
- `DELETE /api/sessions/{id}`：清除会话和保留的证据帧。

浏览器上传限制为 25MB，支持常见视频扩展名。原始上传文件默认在抽帧后删除。API 不提供日历提供器选择，避免前端切换到真实账户。

采集与 OCR 在线程池中运行，因此页面的显式“取消”按钮在本地处理期间仍可提交取消请求。取消标志会在抽帧、选帧和 OCR 边界被检查；命中后删除所有采样帧并停止在日历预检之前。
