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

当前代码不接 OCR、大模型、数据库、日历、视频、语音、HUD 或网页。`evaluate_notice` 不修改输入草案；CLI 唯一写操作是批量结果 JSON。

