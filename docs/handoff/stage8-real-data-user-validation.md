# Stage 8 Real Data & User Validation

> 工程状态：**Stage 8 infrastructure complete**。该状态不等于真实数据或真人用户实验已经执行。

## 1. Git 起始状态

从包含 PR #3 的 `main` 合并提交 `9caa803` 创建 `stage8/real-data-user-validation`；未直接修改或推送 `main`。

## 2. Stage 7 基线测试

进入 Stage 8 前全量测试：`196 passed`。Agent Value 回归：WRONG_EXECUTION 0/20，BUSINESS_COMPLETED 10/20，unsafe tool calls 0，confirmation bypass 0，duplicate execution 0，recovery 4/5。

## 3. Stage 8 新增实现

真实数据 schema 与三重门禁、标注追溯、隐私扫描、现有 OCR/抽取/Safety Gate/事务评测适配、六分类汇总、合成/真实对比、真人日志校验与统计、机器生成报告及测试。

## 4. 真实校园素材数量

NOT EXECUTED（当前已提交 0 张）。

## 5. 真实素材许可与隐私情况

NOT EXECUTED；无真实素材可核验。

## 6. 真实数据最终评测

NOT EXECUTED。

## 7. 合成 vs 真实差异

NOT EXECUTED；不根据空数据推测差异。

## 8. 真人参与人数

NOT EXECUTED（当前 0 人）。

## 9. 真人任务总数

NOT EXECUTED。

## 10. 用户实验结果

NOT EXECUTED。

## 11. 失败案例

NOT EXECUTED。

## 12. 是否出现 WRONG_EXECUTION

NOT EXECUTED。

## 13. SAFE_DEFERRED 数量

NOT EXECUTED。

## 14. SAFE_BLOCKED 数量

NOT EXECUTED。

## 15. 是否存在过度保守迹象

NOT EXECUTED；无真实证据。

## 16. 新发现限制

当前最主要限制是缺少 10—20 张获许可、完成脱敏和双人复核的校园素材，以及 5—8 名签署同意的真人参与者记录。

## 17. 是否修改 Agent 核心

否。只新增 evaluation 适配、验证、分析与报告层。

## 18. 全量测试结果

`226 passed in 46.66s`。

## 19. 当前仍缺少的数据

真实校园素材、对应许可/隐私复核、逐样本标注，以及真人六任务记录。

## 20. Stage 9 建议

尚不建议以真实验证结论进入 Stage 9。先采集并接入真实素材和真人记录，重新运行本入口并审计失败；实体眼镜适配仍应单独立项。
