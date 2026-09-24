# chart-evidence-fusion Specification

## Purpose

让多模态模型负责图表语义理解与最终装配，让 OCR、几何 CV 和布局观测按需提供可追溯证据，并在证据冲突时保留不确定性而不是静默猜测。

## Requirements

### Requirement: Model-led evidence planning

对于需要恢复结构化图表数据的请求，系统 SHALL 允许多模态模型先基于源图像形成语义理解，并按具体不确定点选择 OCR、图表几何观测、布局观测或直接视觉装配。模型可以在第一次工具调用时提交 bounded `observation_scope`，也可以在已有 observation 后提交 bounded `measurement_target`；系统不得要求固定的 inspect、传感器、OCR、装配顺序，也不得自动替模型发起重测。

#### Scenario: Clear chart is assembled directly

- **WHEN** 用户提供清晰且语义完整的图表并要求恢复数据
- **THEN** 模型可以基于多模态视觉理解直接请求 `assemble_spec`
- **AND** 系统不因未调用 `inspect_chart_layout` 或某个图表传感器而拒绝该流程

#### Scenario: Initial scope selects a bounded observer

- **WHEN** 模型能够判断 panel 内的绘图区、图例或轴标签范围
- **THEN** 模型可以在第一次 OCR/CV 调用时提供 `observation_scope`
- **AND** 工具只在授权 panel 内应用该范围并返回实际应用的 scope

#### Scenario: Measurement warning returns control to the model

- **WHEN** 工具返回 warning、候选冲突或低置信度结果
- **THEN** 模型可以接受、舍弃候选、调用另一个观察工具、请求局部补充或放弃该 observation
- **AND** 系统不得因为 warning 自动重复相同的全量测量

### Requirement: Chart observations are attributable evidence

OCR、图表几何传感器和布局观测 SHALL 向模型返回可区分的证据类型、来源、置信度、警告、稳定引用和结构化结果；当工具产生有效的源图像 overlay 时，系统 SHALL 按现有多模态观测协议把它与结构化结果关联返回。工具结果 SHALL 表示观测和候选值，不得把单个工具结果无条件标记为源图像的最终真值。

#### Scenario: OCR and geometry evidence remain distinguishable

- **WHEN** 模型分别调用 OCR 和柱状图或折线图传感器
- **THEN** 下一轮模型上下文能够区分文字证据与几何证据的来源、置信度、稳定引用和警告
- **AND** 每类证据仍保留其适用的像素位置或源图像关联

#### Scenario: Visual evidence remains linked to its observation

- **WHEN** 图表传感器返回结构化数据和源尺寸 overlay
- **THEN** 模型可以将 overlay 与对应工具调用、候选引用和结构化结果关联起来
- **AND** overlay 不改变源图像坐标约定或隐藏工具警告

### Requirement: Evidence conflicts are explicit and recoverable

当模型视觉判断、OCR、几何测量、布局提示或轴校准在同一语义字段上产生实质冲突时，系统 SHALL 保留冲突候选、来源和警告，且 SHALL NOT 静默以任一来源覆盖其他来源。模型 SHALL 能够基于冲突重新观测、降低置信度、保留像素证据或放弃无法可靠恢复的语义值。

#### Scenario: Printed value conflicts with geometry

- **WHEN** OCR 读取的柱值与柱高比例或基准线测量不一致
- **THEN** 模型上下文包含两类候选及其证据和冲突警告
- **AND** 系统不把任一候选自动声明为确定源值

#### Scenario: Layout conflicts with independent pixels

- **WHEN** 模型布局先验与独立检测到的坐标轴、绘图区或基准线不一致
- **THEN** 系统报告布局冲突并保留独立像素检测结果
- **AND** 布局先验不得阻止模型或传感器重新检查源图像

### Requirement: Semantic assembly follows evidence fusion

在图表恢复场景中，模型 SHALL 在融合可用视觉、OCR、几何和布局证据后请求 `assemble_spec`；`assemble_spec` 的成功 SHALL 只表示 ChartSpec 结构和字段合法，不得被解释为图像事实已经经过视觉验证。无法解决的关键值 SHALL 被明确标记为不确定、保留为像素证据，或不纳入确定性语义数据集。

#### Scenario: Valid assembly is structurally but not visually overclaimed

- **WHEN** 模型请求 `assemble_spec` 并得到合法 ChartSpec
- **THEN** 系统可以继续执行生成流程，且生成与审核边界仍会进行代码侧
  语义校验
- **AND** 模型不能仅凭装配成功声称所有数值都已被源图像确认

#### Scenario: Unresolved value blocks a certain claim

- **WHEN** 关键数据值在视觉、OCR 和几何证据之间仍无法解决
- **THEN** 模型不把该值作为确定事实写入最终解释
- **AND** 最终结果保留警告、候选值或明确的未解析状态

### Requirement: Measurement evidence is validated when referenced

当 ChartSpec 使用图表测量结果时，证据融合流程 SHALL 只验证请求通过 `measurement_ref + evidence_refs` 实际引用的 session、attachment、panel、attempt 和 refs。有效引用 SHALL 形成 ChartSpec provenance；未引用候选、普通 warning 和未解析标签不得成为组装门禁，也不得被静默写入最终数据。

#### Scenario: Referenced valid evidence permits assembly

- **WHEN** 模型引用当前来源和 attempt 中的合法 refs
- **THEN** 系统校验这些 refs 并保存来源摘要和适用 warning
- **AND** 组装不要求独立 evidence decision 状态

#### Scenario: Unreferenced false candidates do not block assembly

- **WHEN** measurement observation 同时包含有效候选和图例色块等误检
- **THEN** 组装器只处理请求中实际引用的候选
- **AND** 不要求重新测量或显式舍弃其余候选

#### Scenario: Invalid referenced evidence blocks only dependent assembly

- **WHEN** 被引用 ref 不存在、跨来源或缺少必要结构
- **THEN** 系统返回定位到该 ref 的错误
- **AND** 模型可以改正引用、改用其他证据或停止

### Requirement: Gate failures provide a bounded recovery action

证据引用或组装校验失败 SHALL 返回有界的原因、位置、当前来源范围和可选修复提示。修复提示可以包括补充观察、局部测量、忽略候选、改用视觉证据或停止，但 SHALL 作为建议而非代码拥有的唯一下一动作；系统不得自动执行修复，也不得要求模型猜测缺失数据。

#### Scenario: Evidence issue suggests targeted observation

- **WHEN** 当前候选的基准线、文字、系列关系或局部几何仍不确定
- **THEN** 结果指出相关 ref/字段和可用 scope/target 建议
- **AND** 主 Agent可以自主选择该建议或其他同范围合法动作

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 主 Agent不再补充证据，或补充后仍不能解决关键字段
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用未确认候选自动替代模型判断

### Requirement: Direct visual assembly remains compatible

对于没有采用测量证据、且模型直接基于清晰源图视觉理解组装合法 ChartSpec 的请求，系统 SHALL 保持直接装配路径。当前 run 曾产生但未被引用的 observation SHALL 留在内部历史中，不得要求模型提交 abandoned decision；该路径仍不得绕过 ChartSpec 结构校验和生成审核。

#### Scenario: No measurement evidence is required

- **WHEN** 模型没有引用测量工具结果而提交合法 ChartSpec 或 collection
- **THEN** 系统完成结构装配
- **AND** 不要求伪造 measurement attempt 或 decision

#### Scenario: Unused observation remains auditable

- **WHEN** 模型改用视觉或其他合法证据而未引用已有 measurement observation
- **THEN** observation 继续保留在内部历史
- **AND** 不阻塞当前装配

### Requirement: Semantic labels remain separate from evidence references

证据引用、CV/OCR 观测和 VLM 语义判断 SHALL 使用不同字段表达。VLM 可以根据 overlay、文字和几何关系把 `S1` 映射为真实系列名称或角色，但 `S1`、`B1` 等引用不得被传感器或装配器直接当作用户可见标签。

#### Scenario: Model resolves a series reference

- **WHEN** overlay 标记 `S1` 且 OCR 或源图例显示一个候选名称
- **THEN** 主 Agent 可以将 `S1` 映射为该真实系列名称并在装配时使用
- **AND** 原始测量结果仍保留 `S1` 作为可追踪证据引用

#### Scenario: Unresolved series stays unresolved

- **WHEN** 主 Agent 无法可靠把 `S1` 关联到真实图例名称
- **THEN** 系统保留 `label: null` 或明确的 unresolved 状态
- **AND** 不得把 `series_1` 作为最终图例名称
