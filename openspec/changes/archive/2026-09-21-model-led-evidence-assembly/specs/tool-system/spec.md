## MODIFIED Requirements

### Requirement: Chart measurement tools share a bounded focus target

柱状图、折线图、散点图和饼图测量工具 SHALL 支持统一的可选 `observation_scope` 和 `measurement_target`。`observation_scope` 用于第一次观察，支持当前 panel 内的归一化或源坐标 include/exclude 区域以及目标角色；`measurement_target` 用于已有 attempt 后的候选引用或局部补充。模型不需要提交内部文件路径、完整 mask 字节或伪造 session 身份。

#### Scenario: Initial observation uses a model-provided scope

- **WHEN** 主 Agent 第一次调用图表测量工具并提供 `observation_scope`
- **THEN** 工具在当前授权 panel 内解析该 scope 并返回实际应用区域
- **AND** 工具创建普通 observation attempt，不要求已有 measurement session 或父 attempt

#### Scenario: Initial observation can use normal detection

- **WHEN** 主 Agent 未提供 `observation_scope`
- **THEN** 工具在当前授权 panel 或图表范围执行一次基础测量
- **AND** 返回候选、质量信息、稳定证据引用和可关联 overlay

#### Scenario: Focused measurement resolves current candidates

- **WHEN** 主 Agent 调用同一图表测量工具并提供当前 attempt 的 `measurement_target`
- **THEN** 工具根据 refs 或区域执行 `include` 或 `exclude` focus
- **AND** 新结果记录父 attempt、target 引用和实际应用的搜索范围

### Requirement: Focused measurement never silently widens its search scope

当工具收到有效的 `observation_scope` 或 `measurement_target` 时，工具 SHALL 返回实际应用的范围、坐标空间和 overlay。若区域没有足够证据，工具 SHALL 返回有界的 `focus_empty`、`focus_insufficient` 或等价结果，且不得静默回退到整个 panel 或源图。

#### Scenario: Applied scope is observable

- **WHEN** 初次或定向范围成功应用
- **THEN** 工具结果包含 requested、applied、坐标空间、搜索区域和对应 overlay
- **AND** 主 Agent 可以判断结果是否来自指定区域

#### Scenario: Focus failure remains local

- **WHEN** 范围没有检测到候选或无法生成有效 mask
- **THEN** 工具返回局部失败或不充分状态及原因
- **AND** 工具不扩大范围、不创建隐式全量 attempt

### Requirement: Tool output separates evidence references from semantic labels

图表测量工具 SHALL 在结构化结果和 overlay 中返回稳定的候选引用，并 SHALL 将引用、检测序号、系列内部身份和可选的人类可读 label 分开表达。未解析的 label SHALL 保持 null 或 unresolved；模型可以在组装时提供语义映射，但工具不得把内部引用作为最终业务名称。

#### Scenario: Candidate can be selected or discarded

- **WHEN** 工具检测到多个柱体、系列、轨迹、散点或扇区
- **THEN** 每个候选具有有界引用，且结构化结果和 overlay 使用同一引用
- **AND** 主 Agent 可以在一次组装决策中选择或舍弃候选

#### Scenario: Internal identity is not a semantic label

- **WHEN** 工具无法从图例或文字证据解析真实系列名称
- **THEN** 工具返回内部引用和 `label: null` 或 unresolved 状态
- **AND** render 或 assemble 层不得自动把内部引用绘制成最终业务标签
