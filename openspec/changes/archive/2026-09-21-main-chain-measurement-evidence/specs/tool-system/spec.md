## ADDED Requirements

### Requirement: Chart measurement tools share a bounded focus target

柱状图、折线图、散点图和饼图测量工具 SHALL 支持统一的可选 `measurement_target` 参数。该参数 SHALL 支持引用已有候选或提供有界区域、`include`/`exclude` 模式、受影响字段和原因；模型不需要提交内部文件路径、session 标识或完整 mask 字节。未提供 target 时工具执行一次基础测量，提供 target 时工具只执行对应的局部补充测量。

#### Scenario: Initial measurement uses the normal scope

- **WHEN** 主 Agent 调用图表测量工具但未提供 `measurement_target`
- **THEN** 工具在当前授权 attachment 和 panel 范围内执行一次基础测量
- **AND** 返回候选、质量信息、稳定证据引用和可关联 overlay

#### Scenario: Focused measurement resolves candidate references

- **WHEN** 主 Agent 调用同一图表测量工具并提供当前 attempt 中的候选引用
- **THEN** 工具根据引用解析对应的几何区域并执行 `include` 或 `exclude` focus
- **AND** 新结果记录父 attempt、target 引用和实际应用的搜索范围

#### Scenario: Explicit region is bounded

- **WHEN** 主 Agent 请求的局部区域无法通过已有引用表达
- **THEN** 工具允许使用有界源图 bbox 或 polygon 作为 target
- **AND** 工具拒绝越界、空区域、跨 panel 或无法归属当前 attachment 的 target

### Requirement: Focused measurement never silently widens its search scope

当测量工具收到有效的 focused target 时，工具 SHALL 返回实际应用的 target 状态和搜索范围。若 mask 或局部区域没有足够证据，工具 SHALL 返回有界的 `focus_empty`、`focus_insufficient` 或等价非接受结果，且不得静默回退到整个 panel 或源图。

#### Scenario: Applied focus is observable

- **WHEN** focused target 成功应用
- **THEN** 工具结果包含 `requested`、`applied`、target 引用、搜索范围和对应 overlay
- **AND** 主 Agent 可以判断本次结果是否真正来自局部测量

#### Scenario: Focus failure remains local

- **WHEN** focused target 没有检测到候选或无法生成有效 mask
- **THEN** 工具返回局部失败或不充分状态及原因
- **AND** 工具不扩大范围、不创建隐式全量 attempt

### Requirement: Tool output separates evidence references from semantic labels

图表测量工具 SHALL 在结构化结果和 overlay 中返回稳定的候选引用，并 SHALL 将引用、检测序号、系列内部身份和可选的人类可读 label 分开表达。未解析的 label SHALL 保持 null 或 unresolved，不得使用 `series_1` 等内部引用作为用户可见名称。

#### Scenario: Candidate can be cross-referenced

- **WHEN** 工具检测到多个柱体、系列、轨迹、散点或扇区
- **THEN** 每个候选具有有界引用，且结构化结果和 overlay 使用同一引用
- **AND** 主 Agent 可以基于引用发起下一次 focused measurement

#### Scenario: Internal identity is not a semantic label

- **WHEN** 工具无法从图例或文字证据解析真实系列名称
- **THEN** 工具返回内部引用和 `label: null` 或 unresolved 状态
- **AND** render 或 assemble 层不得自动把内部引用绘制成最终业务标签
