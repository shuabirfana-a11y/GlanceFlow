# 见程 GlanceFlow

见程是面向校园线下高价值时限通知的第一视角可信行动编译智能体。本仓库当前仅实现 Stage 1：结构化日程草案、确定性行动安全门、CLI 演示和自动化测试。

当前版本不包含 OCR、图像或视频识别、大模型 API、日历写入、语音、HUD、网页前端和数据库。任何未通过安全门的草案都不能进入确认，更不能触发外部操作。

## Windows 环境安装

```powershell
C:\x\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install --editable .
```

项目要求 Python 3.11 或更高版本。`tzdata` 用于确保 Windows 上的 `zoneinfo` 能识别 `Asia/Shanghai` 等 IANA 时区。

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

测试覆盖 Pydantic 模型、ID 与时区校验、JSON 往返、安全规则、四种状态、状态优先级、输入不变性、CLI 单文件/批量模式及真实输出文件生成。

## 代码入口

- `src\glanceflow\domain\models.py`：草案与证据数据结构。
- `src\glanceflow\safety\rules.py`：15 条独立确定性规则。
- `src\glanceflow\safety\gate.py`：统一入口 `evaluate_notice(...)`。
- `src\glanceflow\cli.py`：Stage 1 CLI。
- `examples\`：九个人工测试草案。

下一阶段仅计划接入一个受约束的 OCR 适配接口：OCR 输出 `EvidenceLine`，提取器输出引用真实 `line_id` 的 `NoticePackageDraft`，随后仍必须经过现有安全门。详见 `PROJECT_SPEC.md`。

