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

## Stage 3 候选任务（未实现）

- [ ] 定义无厂商依赖的 `CalendarPort`
- [ ] 定义创建、回读、补偿回滚和精准撤销数据契约
- [ ] 使用内存假日历测试幂等和半成功事务
- [ ] 在获得单独授权前不接入 OAuth 或真实日历
