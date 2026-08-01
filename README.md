# 见程 GlanceFlow

见程是面向校园线下高价值时限通知的第一视角可信行动编译智能体。本仓库当前实现 Stage 1 的结构化日程与行动安全门，以及 Stage 2 的本地 OCR 证据链、图像质量门和确定性字段抽取。

当前版本不包含视频、语音、大模型 API、日历写入、OAuth、HUD、网页前端和数据库。任何未通过质量门、抽取约束与安全门的候选都不能进入确认，更不能触发外部操作。

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

测试覆盖原31项 Stage 1 行为，以及 OCR 异常、真实 bbox、唯一 line_id、中文路径、质量阈值、字段证据绑定、十张图片端到端状态和两种图片 CLI 模式。

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

十张图片均为程序生成的人工测试素材，不代表任何真实学校通知；脚本只引用本机微软雅黑，不复制字体文件。下一阶段仅计划定义真实日历事务端口、幂等键、回读和补偿接口，默认仍使用内存假实现测试，不在本阶段接入 Google Calendar。
