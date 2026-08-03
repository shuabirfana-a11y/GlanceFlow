# Stage 8 真人用户实验

## 当前状态

**尚未执行真人用户实验。** 当前没有真实参与者记录，不计算 0%、0 秒或 0 分作为实验结果。分析工具不会自动生成参与者或任务行。

目标是在参与者签署知情同意后，由 5—8 名真实参与者分别完成 T1—T6。只使用匿名编号 `P01`、`P02`……，不记录姓名、学号或联系方式。

## 自定义 1—5 分量表

这不是 SUS 或 NASA-TLX，也不换算标准量表分数：

- HUD 理解度：1 完全不理解，5 完全理解；
- 主观可信度：1 完全不信任，5 非常信任；
- 使用负担：1 非常低，5 非常高；
- 继续使用意愿：1 完全不愿意，5 非常愿意。

每条任务记录必须包含完成状态、耗时、确认/澄清/重拍次数、误操作、四项评分及观察信息。参与者与任务组合必须唯一。

## 运行

```powershell
.\.venv\Scripts\python.exe evaluation\user_study\analysis_script.py
```

输出位于 `outputs/evaluation/user_study/`：

- `user_study_results.csv`
- `user_study_summary.json`
- `user_study_report.md`

Markdown 数字全部由 CSV 机器记录自动生成。空模板只输出 `NOT EXECUTED` 和“尚未执行真人用户实验。”。
