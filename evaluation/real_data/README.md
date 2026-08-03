# Stage 8 真实校园小样本数据集

**No real campus samples are currently committed.**

当前真实许可素材数量为 0；真实评测状态为 `NOT EXECUTED`。本目录不会以合成海报、网络图片或占位图片冒充真实校园素材。

## 数据边界

- `manifest.csv` 只接受 `RD-001` 格式的真实样本；46 个固定种子合成样本继续保存在 `evaluation/dataset/`，两者不混算。
- 原始未脱敏文件必须留在 Git 之外；只有获得许可、完成隐私复核并脱敏的文件才能进入 `sanitized/`。
- 每个样本须有 `annotations/RD-xxx.json`，缺失字段使用 `null`，真实歧义写入 `ambiguity_notes`。
- 失败样本必须保留。若证明确为标注错误，修改时在 `revision_history` 写明时间、人员与原因。
- 自动公开结果不保存 OCR 全文，并检查手机号、邮箱、学号、带标签姓名、二维码原内容和个人本地路径。

## 正式清单门禁

每行必须同时满足：`source_type=REAL`、`permission_confirmed=true`、`privacy_reviewed=true`、`sanitized=true`、`annotation_status=APPROVED`，且图片位于 `evaluation/real_data/sanitized/`。标注者、复核者及 sample_id 必须和 JSON 一致。

## 运行

```powershell
.\.venv\Scripts\python.exe evaluation\real_data\scripts\validate_manifest.py
.\.venv\Scripts\python.exe -m glanceflow.evaluation.real_data
.\.venv\Scripts\python.exe evaluation\real_data\scripts\compare_real_vs_synthetic.py
```

结果写入 `outputs/evaluation/real_data/`。没有真实样本时仍生成可解析的 JSON、CSV、Markdown，但比例和结论显示 `NOT EXECUTED`。
