# Changelog

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

