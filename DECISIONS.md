# Architecture Decisions

## ADR-001：模型边界和安全门双层时区校验

Pydantic 拒绝无时区 datetime，防止非法 JSON 进入业务层。安全门仍实现 `GF-TIME-001/002`，用于防御绕过正常构造路径的内部对象。Windows 通过 `tzdata` 为 `zoneinfo` 提供 IANA 数据。

## ADR-002：规则全部执行

每次评估固定执行 15 条规则，不首错即停。这样 CLI 和未来 HUD 可以一次呈现全部问题，测试也能验证状态优先级。

## ADR-003：状态由规则类别和固定优先级汇总

确定性矛盾、重复和非法字段组合映射到 `CONTRADICTION_BLOCKED`；证据引用、来源和清晰度问题映射到 `RECAPTURE_REQUIRED`；可由用户补充的信息映射到 `NEED_USER_INPUT`。

## ADR-004：重复检测只使用当前阶段可证明的数据

仅在标准化标题相同且 `event_start` 完全相同时阻断，不使用模糊模型推断。批量 CLI 将此前成功加载的草案作为重复检测上下文。

## ADR-005：证据行 ID 在草案内唯一

重复 `line_id` 会使证据反查产生歧义，因此在 Pydantic 模型边界直接拒绝，而不是让后续规则任意选择一行。

## ADR-006：Stage 1 无外部副作用

Stage 1 检查点不接 OCR、大模型、数据库、日历、视频、语音、HUD 或网页。`evaluate_notice` 不修改输入草案；Stage 1 CLI 唯一写操作是批量结果 JSON。Stage 2 在后续独立提交中增加本地 OCR，但仍没有任何外部执行。

## ADR-007：使用 RapidOCR ONNX 本地 CPU 提供器

本机没有 Tesseract，Windows OCR 能力查询需要管理员权限。pip 实际解析确认 RapidOCR ONNX、ONNX Runtime、OpenCV、Pillow 和 NumPy均提供 Python 3.13 Windows 轮子。实测能识别中文并返回置信度和真实坐标，因此选择 `rapidocr-onnxruntime 1.2.3`。它自带默认模型、运行时离线、无需 GPU，Apache-2.0 许可证适合比赛和开源演示。

## ADR-008：质量失败不伪造草案

低分辨率、模糊、全黑、无文本、解码失败或 OCR 异常直接生成 `ImagePipelineResult(RECAPTURE_REQUIRED)`。因为缺少合法时间时 `NoticePackageDraft` 无法成立，抽取器返回结构化失败而不是填充虚假时间。

## ADR-009：OCR 行与视觉行分离

RapidOCR 的每个真实输出片段保持为独立 `EvidenceLine`。抽取器可以根据 bbox 将同一视觉行的片段组合用于正则解析，但字段保存所有组成片段的真实 line_id，且不生成或修改坐标。

## ADR-010：缺失证据不等于低置信度

Stage 1 的 `GF-CONFIDENCE-001` 仅在字段已有证据引用时检查字段置信度。否则同一缺失地点会同时触发“需要补充”和“重新采集”，违反状态语义。缺失引用继续由 `GF-EVIDENCE-001` 处理；该调整向后兼容并有回归测试。

## ADR-011：OCR 结果模型强制证据不变量

`OcrResult` 在模型边界强制 line_id 唯一、source_frame_id 一致、bbox 存在且位于图片边界。中文文件名保留 Unicode 字符生成稳定帧 ID，避免多个中文文件全部碰撞为 `frame-image`。
