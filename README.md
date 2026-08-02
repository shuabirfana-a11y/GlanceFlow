# 见程 GlanceFlow

见程是面向校园线下高价值时限通知的第一视角可信行动编译智能体。本仓库实现 Stage 1 行动安全门、Stage 2 本地 OCR 证据链、Stage 3 可信日历事务层，以及 Stage 4 本地第一视角眼镜交互模拟器。

Stage 3 默认使用隔离的内存日历，支持 Action Preflight｜行动预检、结构化确认、原子创建、event_id 回读、补偿回滚和精准撤销。Google Calendar 适配器已经实现并通过假服务契约测试，但当前没有测试凭据，因此没有进行或声称真实 Google 调用。

Stage 4 是“眼镜工作流模拟”，不是已经部署到真实眼镜设备。它以本地短视频或浏览器短时相机采集模拟第一视角输入，只在明确的“帮我安排”指令后采集约 3 秒，自动选帧并复用既有 OCR、安全门和可信日历事务。默认日历仍为内存实现。

Stage 5 不增加业务功能，只提供固定种子评测数据集、三系统同集对比、七项消融、指标与图表生成、失败案例分析、用户测试模板和初赛技术材料。所有结果来自程序运行，不手填成绩。

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

运行本地第一视角交互演示：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.cli wearable-demo
```

演示真实处理六个场景：正常创建并回读、全程模糊重拍、星期矛盾阻断、冲突等待二次确认、移动中确认延后，以及按 event_id 撤销。结果写入 `outputs\stage4_results.json`。

启动本地浏览器模拟器：

```powershell
.\.venv\Scripts\python.exe -m glanceflow.simulator.app
```

然后打开 `http://127.0.0.1:8765/`。浏览器支持上传短视频；在浏览器允许且用户主动点击时，也可调用 `getUserMedia + MediaRecorder` 采集约 2.8 秒并自动停止所有相机轨道。若浏览器不支持语音识别，页面始终提供明显的文本指令降级入口。

模拟器只接受四类确定性指令：`帮我安排`、`确认`、`取消`、`撤销上一步`（及代码内列出的少量固定同义词）。未知表达或低置信度结果不触发状态变化和外部写入。

生成并运行完整 Stage 5 评测：

```powershell
.\.venv\Scripts\python.exe evaluation\scripts\generate_dataset.py
.\.venv\Scripts\python.exe -m glanceflow.evaluation.run_all
```

评测使用 46 个固定种子人工案例，输出到 `outputs\evaluation\`。三个系统共享同一输入与 OCR 观测；Baseline A 是简单正则直接写入，Baseline B 是正式抽取器但无安全门，Full System 使用完整可信闭环。七项消融只在 `glanceflow.evaluation` 实验适配层生效。

错误执行率的分母是实际执行包数，分母为零时显示 `N/A`；有效覆盖率和误拒率以应执行通知为分母，因此全部拒绝不会获得虚假高分。耗时只代表当前 Windows 本地 CPU 模拟器。

## Stage 4 隐私与安全边界

- 不持续录音或录像；没有明确的安排指令就不开始采集。
- 每次只处理触发后的最多 3 秒，较长输入不会扩大处理窗口。
- 浏览器上传的原始临时视频在抽帧后默认删除；未选中的帧随即删除。
- 只保留自动选中的证据帧到当前会话目录；“清除并新建会话”会删除它。
- 画面质量不足时直接进入 `RECAPTURE`，不会强行挑选一个坏帧。
- `MOVING` 或 `UNKNOWN` 姿态可以生成待确认草案，但禁止确认、创建和撤销日历事件。
- 冲突不会自动改时间，也不会静默创建；必须在冲突 HUD 出现后明确确认。
- 模拟层只持有 `TrustedSchedulingService`，不直接持有或调用 `CalendarPort`。

## 日历事务保证

- 只有 `READY_TO_CONFIRM` 且安全门允许确认的草案能进入 Action Preflight｜行动预检。
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

测试覆盖 Stage 1/2 行为、内存 CalendarPort、确认、重复、冲突、幂等超时重试、原子创建、回读验证、补偿失败、精准撤销、Google 契约、Stage 4 交互，以及 Stage 5 清单、指标、零分母、同集对比、消融隔离、图表、输出追溯和用户测试真实性门禁。

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
- `src\glanceflow\calendar\`：厂商无关模型、端口、内存/Google提供器、Action Preflight｜行动预检、验证、回滚和事务状态机。
- `src\glanceflow\application\`：可信调度服务与内存演示编排。
- `src\glanceflow\wearable\`：采集端口、自动选帧、语音、姿态、HUD 与会话模型。
- `src\glanceflow\application\glanceflow_service.py`：串接眼镜模拟输入与既有可信日历事务的唯一编排层。
- `src\glanceflow\simulator\`：FastAPI 本地接口和原生 HTML/CSS/JS 模拟器。
- `data\generate_synthetic_videos.py`：固定种子的八段合成短视频生成器。
- `evaluation\dataset\`：46 例人工构造评测素材、逐例标注和统一清单。
- `src\glanceflow\evaluation\`：基线、消融、指标、可靠性试验、报告和图表生成。
- `outputs\evaluation\`：自动生成的 JSON、CSV、Markdown、scorecard 和七张图。
- `docs\competition\`：初赛项目说明、架构、创新、评测、隐私、限制、三分钟脚本与评委问答。

十张图片和八段短视频均为程序生成的人工测试素材，不代表任何真实学校通知。任何后续真实设备适配都必须实现现有端口，并继续经过质量门、安全门、明确确认和可信日历事务。
