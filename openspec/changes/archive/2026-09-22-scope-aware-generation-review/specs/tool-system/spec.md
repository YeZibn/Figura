## ADDED Requirements

### Requirement: Scope-aware chart tools expose bounded contracts

图表测量、assemble_spec 和 render_chart 的模型可见 JSON Schema SHALL 显式表达
`observation_scope`、`measurement_target`、`generation_context`、coverage 和候选引用的
适用关系、枚举、数量上限与字段描述。工具描述 SHALL 用简明中文说明何时使用、何时不要
使用、返回什么证据，以及工具不会替模型决定什么。

#### Scenario: Model can distinguish first observation from focused repair

- **WHEN** 主 Agent 查看图表测量工具定义
- **THEN** schema 和描述明确 observation_scope 用于当前调用范围
- **AND** measurement_target 只用于已有 attempt 的局部补充
- **AND** 不暗示工具会自动重测或自动选择业务系列

### Requirement: Scope violations return structured tool errors

工具收到与 generation context 不一致的 attachment、panel、bbox、measurement reference
或 coverage 时 SHALL 返回字段级结构化错误，且不得读取或测量越界区域。错误 SHALL 包含
可恢复的 action hint，例如重新绑定 source 或请求同 panel evidence。

#### Scenario: Measurement cannot widen to the dashboard

- **WHEN** evidence repair 的工具参数省略 panel scope 并试图扫描整张附件
- **THEN** 工具拒绝调用或要求明确的同范围 target
- **AND** 不返回可被误当作当前 candidate 证据的全图结果

### Requirement: Tool results keep evidence separate from semantic decisions

测量工具 SHALL 返回稳定 evidence refs、effective scope、候选几何/数值和质量 warning；
工具不得直接返回代表系列、删除系列或 ChartSpec 已接受语义，除非这些是主 Agent 在参数
中明确提交的决策并可追溯。

#### Scenario: Agent decision is visible after tool observation

- **WHEN** 工具发现多个可能的 bar candidates
- **THEN** result 仅提供候选与证据引用
- **AND** 后续 assemble 请求必须显式携带 selected/discarded refs 与 coverage basis

