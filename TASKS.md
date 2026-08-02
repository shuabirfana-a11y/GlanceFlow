# Tasks

## Stage 1

- [x] 检查 Windows、Python 和 Git 环境
- [x] 创建 `.venv` 并安装 Pydantic v2、pytest、tzdata
- [x] 建立 `src` 项目结构和严格数据模型
- [x] 实现 15 条确定性安全规则
- [x] 实现状态优先级和统一安全门入口
- [x] 创建九个人工 JSON 样例
- [x] 实现单文件与批量 CLI
- [x] 生成 `outputs\stage1_results.json`
- [x] 覆盖模型、规则、状态和 CLI 自动化测试
- [x] 主动审查证据 ID 唯一性和输入不变性
- [x] 同步 README、规范、决策和变更记录

## Stage 2

- [x] 定义只输出真实 `EvidenceLine` 的 OCR Provider 协议
- [x] 选择并实测本地 RapidOCR ONNX 提供器
- [x] 增加集中阈值的图像质量门
- [x] 定义从 OCR 行到候选草案的受约束确定性抽取
- [x] 生成10张人工图片与 ground truth JSON
- [x] 完成图片单文件/批量 CLI 与 Stage 2 输出
- [x] 验证四种安全状态、真实 bbox 和 line_id 绑定
- [x] 完成主动审查、有限优化和全量回归

## Stage 3

- [x] 定义无厂商依赖的 `CalendarPort` 和事务模型
- [x] 实现隔离内存日历与完整故障注入
- [x] 实现 Action Preflight｜行动预检（重复与冲突检查）和结构化二次确认
- [x] 实现单/双事件原子创建、event_id 回读与逐字段验证
- [x] 实现补偿回滚、失败留痕和精准撤销
- [x] 验证首/次事件超时后的幂等重试
- [x] 实现 Google Calendar 官方客户端契约适配器
- [x] 明确无凭据情况下不执行真实 Google 调用
- [x] 实现 `calendar-demo` 和 Stage 3 输出
- [x] 完成主动审查与全量回归

## Stage 4 候选任务（未实现）

- [ ] 定义短时第一视角帧采集端口
- [ ] 定义明确语音触发与结构化确认事件
- [ ] 定义只读 HUD 状态呈现模型
- [ ] 保持交互层无 CalendarPort 直接写权限
