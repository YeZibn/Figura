## MODIFIED Requirements

### Requirement: Tool output separates evidence references from semantic labels

图表测量工具 SHALL 在结构化结果和 overlay 中返回稳定的候选引用，并将引用、检测序号、系列内部身份、位置、scope、质量信息和可选的人类可读 label 分开表达。未解析 label SHALL 保持 null 或 unresolved；工具不得把内部引用当作最终业务名称，也不得返回候选的 selected/discarded 生命周期状态。

#### Scenario: Candidates are returned as addressable evidence

- **WHEN** 工具检测到多个柱体、系列、轨迹、散点或扇区
- **THEN** 每个候选具有有界引用，且结构化结果和 overlay 使用同一引用
- **AND** 主 Agent 可以在后续工具调用中只引用实际使用的候选，不要求列举其余候选

#### Scenario: Internal identity is not a semantic label

- **WHEN** 工具无法从图例或文字证据解析真实系列名称
- **THEN** 工具返回内部引用、series metadata 和 `label: null` 或 unresolved 状态
- **AND** render 或 assemble 层不得自动把内部引用绘制成最终业务标签

### Requirement: Tool results keep evidence separate from semantic decisions

测量工具 SHALL 返回候选几何/数值、稳定 `measurement_ref` 与 `evidence_refs`、effective scope、质量元数据和系列元数据。`assemble_spec` SHALL 接收实际使用的 measurement/evidence refs、必要来源范围及图表意图，并 SHALL 校验引用存在性、来源归属和 ChartSpec 结构；工具 schema 和运行时不得接受、转换或兼容 `measurement_decision`、selected refs、discarded refs 或 decision status。

#### Scenario: Assembly uses only the referenced candidate evidence

- **WHEN** 主 Agent 根据图像和候选结果提交 `measurement_ref + evidence_refs` 以及图表意图
- **THEN** assemble 只校验并保存这些实际引用的候选及其来源
- **AND** 同次 measurement 中未引用的候选既不需要 decision，也不阻塞组装

#### Scenario: Invalid references return a focused error

- **WHEN** assembly 引用不存在、越界或跨来源的 evidence ref
- **THEN** 工具返回指向实际输入字段的结构化校验错误
- **AND** 不自动重测或将质量状态转换为 selected/discarded decision

#### Scenario: Legacy decision fields are not part of the model-visible contract

- **WHEN** 模型读取 measurement 或 assembly 工具 JSON Schema
- **THEN** schema 只声明候选 refs、scope、质量/系列信息与 assembly 所需的 ChartSpec 输入
- **AND** 不暴露 `measurement_decision`、`selected_refs`、`discarded_refs` 或其兼容别名
