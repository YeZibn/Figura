## ADDED Requirements

### Requirement: VLM review receives a precise source scope and task contract

每个 source-linked candidate 的 VLM review SHALL 接收候选图、不可变 ChartSpec、
generation context 和由授权 panel handoff 解析出的来源裁剪。review prompt SHALL 明确
目标图表类型、任务模式、represented/omitted series 和需要检查的范围；不得让 VLM 从整
张 dashboard 自行猜测本次任务。

#### Scenario: Transform review checks the selected panel only

- **WHEN** candidate 是左侧 bar panel 到 pie 的 transform
- **THEN** review 输入包含左侧 panel crop 和 pie candidate
- **AND** VLM 检查 selected series 的数值、类别、类型转换和标签
- **AND** 不因为右侧 line panel 未生成而失败

#### Scenario: Missing scope is an explicit review failure

- **WHEN** panel handoff 无法解析或候选上下文缺少 source scope
- **THEN** review 返回 `source_scope_unavailable` 或 legacy/unknown 诊断
- **AND** 对声称 source-linked 的 candidate 不得把整张原图默认为正确来源

### Requirement: Review remains one tool-free VLM decision per candidate attempt

单个 candidate attempt SHALL 只进行一次 VLM review call；该 call 不得调用 OCR、CV、
measurement、layout inspection 或其他工具。需要补证据时，review SHALL 返回结构化的
`evidence_needed` repair kind，由主 Agent 在 gate 允许的范围内处理后创建新 attempt。

#### Scenario: Review does not hide a second measurement pass

- **WHEN** candidate 进入审核
- **THEN** 审核过程的 tool count 为零且只产生一份结构化 review decision
- **AND** 任何后续测量必须属于显式的 evidence repair attempt，而非审核内部隐式调用

### Requirement: Review checks differ by task mode

VLM review SHALL 使用以下最小语义边界：`reconstruct` 检查声明范围内的完整来源保真度；
`transform` 检查目标类型和选定数据是否正确转换；`summarize` 检查摘要范围与数值代表性；
`synthesize` 不得声称源图逐值还原，但仍检查候选自身的结构与可读性。review SHALL 将
超出当前模式的差异标记为 informational，而不是无依据地判 fail。

#### Scenario: Omitted target is informational in an explicit transform

- **WHEN** transform context 明确只表示 Actual 并记录 Target omitted
- **THEN** review 可以报告 Target omission 作为信息
- **AND** 不得把该 omission 作为缺失来源导致 fail

### Requirement: Review output identifies actionable repair

review decision SHALL 返回 bounded decision、issue code、severity、candidate/attempt
identity 和 repair kind；当问题是证据不足时，诊断 SHALL 指出需要补充的 scope/role 或
证据引用，而不是只返回自由文本“审核失败”。

#### Scenario: Missing value points to a bounded target

- **WHEN** review 发现某个 selected bar 的数值无法确认
- **THEN** decision 标出对应的 series/category/reference target
- **AND** repair kind 为 evidence_needed 或 spec_only
- **AND** 主 Agent 可以据此决定是否补测

