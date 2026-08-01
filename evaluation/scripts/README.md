# 评测脚本

- `generate_dataset.py`：用固定种子生成 46 个完全人工测试案例和逐例标注。
- 统一运行入口位于 `python -m glanceflow.evaluation.run_all`。

重新生成数据集会覆盖同名人工素材，不读取或写入任何真实用户数据。
