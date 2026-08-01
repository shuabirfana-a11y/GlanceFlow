# 见程 GlanceFlow

见程是面向校园线下高价值时限通知的第一视角可信行动编译智能体。本仓库实现 Stage 1 行动安全门、Stage 2 本地 OCR 证据链，以及 Stage 3 可信日历事务层。

Stage 3 默认使用隔离的内存日历，支持预检、结构化确认、原子创建、event_id 回读、补偿回滚和精准撤销。Google Calendar 适配器已经实现并通过假服务契约测试，但当前没有测试凭据，因此没有进行或声称真实 Google 调用。

## Windows 环境安装

```powershell
C:\x\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --editable .
```

项目要求 Python 3.11 或更高版本。`tzdata` 用于确保 Windows 上的 `zoneinfo` 能识别 `Asia/Shanghai` 等 IANA 时区。

Stage 2 使用本地 CPU 方案 `rapidocr-onnxruntime 1.2.3`，默认模型随包安装，运行时不需要网络或 GPU。OCR 返回真实文本片段、置信度和 bbox；OpenCV 通过字节解码支持中文 Windows 路径。

## 使用 CLI

评估单个草案：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli examples\01_valid_event.json
```

批量评估九个人工样例：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli examples
```

批量结果写入 `outputs\stage1_results.json`。批量评估按文件名排序，已评估草案会进入后续草案的重复检查上下文。

识别单张图片：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli extract-image data\synthetic_posters\01_valid_event.png
```

批量识别图片：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli extract-image data\synthetic_posters
```

批量图片结果写入 `outputs\stage2_results.json`。如需可复现的过期判断，可增加：

```powershell
--captured-at 2026-08-01T09:00:00+08:00
```

运行可信日历事务演示：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli calendar-demo
```

演示从 Stage 2 合法图片结果加载草案，真实执行内存日历正常双事件事务与撤销、冲突未接受、第二事件失败回滚、回读不一致回滚，并写入 `outputs\stage3_results.json`。

## 日历事务保证

- 只有 `READY_TO_CONFIRM` 且安全门允许确认的草案能进入预检。
- 用户确认记录标题、开始时间、地点和可选截止时间；字段变化使确认失效。
- 冲突不自动改时间，必须再次设置 `accepted_conflict=True`。
- 主活动与截止事件使用不同角色和幂等键，任一创建或回读失败都会补偿删除已创建部分。
- 回读严格比较标题、实际时刻、时区、地点、通知包 ID、事务 ID 和事件角色。
- 撤销只使用事务记录中的 event_id，不按标题搜索。
- 主活动默认60分钟、截止提醒默认15分钟；这是初赛工程规则，不是 OCR 提取结果。

## Google Calendar 安全边界

适配器使用官方 `google-api-python-client`。仅在同时设置以下环境变量时才可构造真实客户端：

```text
GLANCEFLOW_GOOGLE_CREDENTIALS=<本地未跟踪凭据文件>
GLANCEFLOW_GOOGLE_CALENDAR_ID=<专用测试日历ID>
```

Stage 3 明确拒绝 `primary` 日历，使用最小 `calendar.events` 权限，凭据、token 和本地密钥均被 `.gitignore` 排除。当前环境未提供这两个变量，故只完成适配器代码和契约测试。

## 安全门状态

| 状态 | 含义 | 允许确认 |
|---|---|---|
| `READY_TO_CONFIRM` | 全部规则通过 | 是 |
| `NEED_USER_INPUT` | 信息缺失或时间表达未解析 | 否 |
| `RECAPTURE_REQUIRED` | 证据引用、来源或置信度不可靠 | 否 |
| `CONTRADICTION_BLOCKED` | 时间、字段组合或重复性存在确定性矛盾 | 否 |

优先级为：`CONTRADICTION_BLOCKED > RECAPTURE_REQUIRED > NEED_USER_INPUT > READY_TO_CONFIRM`。安全门始终执行全部 15 条规则并返回每条结果。

## 运行测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

测试覆盖原67项 Stage 1/2 行为，以及内存 CalendarPort、确认、重复、冲突、幂等超时重试、原子创建、回读验证、补偿失败、精准撤销、Google 契约和 Stage 3 CLI。

## 代码入口

- `src\glanceflow\domain\models.py`：草案与证据数据结构。
- `src\glanceflow\safety\rules.py`：15 条独立确定性规则。
- `src\glanceflow\safety\gate.py`：统一入口 `evaluate_notice(...)`。
- `src\glanceflow\cli.py`：Stage 1 CLI。
- `examples\`：九个人工测试草案。
- `src\glanceflow\ocr\`：OCR 协议、RapidOCR 提供器和质量门。
- `src\glanceflow\extraction\`：确定性字段抽取和证据链接。
- `src\glanceflow\pipeline.py`：图片到安全状态的统一管线。
- `data\generate_synthetic_posters.py`：固定种子的人工素材生成脚本。
- `src\glanceflow\calendar\`：厂商无关模型、端口、内存/Google提供器、预检、验证、回滚和事务状态机。
- `src\glanceflow\application\`：可信调度服务与内存演示编排。

十张图片均为程序生成的人工测试素材，不代表任何真实学校通知。下一阶段可定义第一视角短视频帧输入、明确语音触发和只读 HUD 展示接口，但不得绕过现有质量门、安全门和日历确认事务。
