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

## Stage 2 候选任务（未实现）

- [ ] 定义只输出 `EvidenceLine` 的 OCR Provider 协议
- [ ] 定义从 OCR 行到候选草案的受约束提取接口
- [ ] 增加帧质量结果的数据契约
- [ ] 建立 OCR fixture，不接入日历或其他外部执行

