# Changelog

## 0.2.0 - 2026-08-01

### Added

- 本地 RapidOCR ONNX 中文 OCR 提供器及 `OcrProvider` 协议。
- OCR 结果模型、真实 bbox/line_id/source-frame 不变量。
- 集中阈值的图片存在性、格式、解码、分辨率、全黑、模糊和无文本检查。
- 确定性标题、日期时间、地点、截止时间与截止动作抽取。
- 图片到原行动安全门的统一 `process_image` 管线。
- 十张固定种子的人工图片、ground truth 和生成脚本。
- 图片单文件/批量 CLI 及 `stage2_results.json`。
- OCR、质量、抽取、中文路径、证据防伪和端到端测试。

### Changed

- `GF-CONFIDENCE-001` 仅检查已有证据绑定的字段，避免缺失字段被误分类为重采。
- 项目版本升级到 0.2.0，Stage 1 JSON CLI 保持兼容。

### Fixed during review

- 保留纯中文文件名生成唯一稳定 source frame ID。
- 拒绝重复 line_id、跨帧证据、空 bbox 和越界 bbox。
- 调整一张人工素材的地点措辞，消除真实 OCR 产生的多余字符。
- 验证恶意抽取器伪造 line_id 会被原安全门阻止。

## 0.1.0 - 2026-08-01

### Added

- Pydantic v2 领域模型、枚举和 JSON 数据契约。
- 15 条独立行动安全规则及统一安全门。
- 四种最终状态和固定状态优先级。
- 单文件与批量 CLI，批量结果写入 `outputs\stage1_results.json`。
- 九个人工场景和完整 pytest 覆盖。
- Windows IANA 时区支持与项目内 pytest 临时目录。

### Fixed during review

- 增加 `tzdata`，修复精简 Windows Python 无法加载 `Asia/Shanghai`。
- 固定自动化子进程 UTF-8 输出，避免中文 CLI 测试受控制台代码页影响。
- 拒绝草案内重复证据 `line_id`，消除证据反查歧义。
- 验证安全门评估不会修改输入草案。
