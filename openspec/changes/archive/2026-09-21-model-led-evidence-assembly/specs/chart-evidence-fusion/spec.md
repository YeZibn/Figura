## MODIFIED Requirements

### Requirement: Model-led evidence planning

对于需要恢复结构化图表数据的请求，系统 SHALL 允许多模态模型先基于源图像形成语义理解，并按具体不确定点选择 OCR、图表几何观测、布局观测或直接视觉装配。模型可以在第一次工具调用时提交 bounded `observation_scope`，也可以在已有 observation 后提交 bounded `measurement_target`；系统不得要求固定的 inspect、传感器、OCR、装配顺序，也不得自动替模型发起重测。

#### Scenario: Clear chart is assembled directly

- **WHEN** 用户提供清晰且语义完整的图表并要求恢复数据
- **THEN** 模型可以基于多模态视觉理解直接请求 `assemble_spec`
- **AND** 系统不因未调用某个布局或测量工具而拒绝该流程

#### Scenario: Initial scope selects a bounded observer

- **WHEN** 模型能够判断 panel 内的绘图区、图例或轴标签范围
- **THEN** 模型可以在第一次 OCR/CV 调用时提供 `observation_scope`
- **AND** 工具只在授权 panel 内应用该范围并返回实际应用的 scope

#### Scenario: Measurement warning returns control to the model

- **WHEN** 工具返回 warning、候选冲突或低置信度结果
- **THEN** 模型可以接受、舍弃候选、调用另一个观察工具、请求局部补充或放弃该 observation
- **AND** 系统不得因为 warning 自动重复相同的全量测量

### Requirement: Measurement evidence must pass an acceptance gate before assembly

当 ChartSpec 使用图表测量结果时，证据融合流程 SHALL 确认 measurement session、attachment、panel、attempt 和主 Agent 的 evidence decision 存在。系统不得要求整个 attempt 先成为全局 `accepted`；组装器 SHALL 只校验被选中的 refs 是否真实存在、来源正确、范围合法并满足所使用字段的必要结构。测量 warning、未解析的语义标签和未选中的候选不得被静默当作最终事实，但也不得阻塞模型选择其他证据。

#### Scenario: Selected valid evidence permits assembly

- **WHEN** 当前 attachment 和 panel 的测量 attempt 存在，且主 Agent 选择了合法 evidence refs
- **THEN** 模型可以将这些 refs 作为 ChartSpec provenance 请求 `assemble_spec`
- **AND** ChartSpec 保留被选择的来源摘要、warning 和证据决策

#### Scenario: Unselected false candidates do not block assembly

- **WHEN** 测量结果包含图例色块、文字或其他误检候选，且主 Agent 在 decision 中舍弃它们
- **THEN** 组装器只校验剩余 selected refs
- **AND** 不因同一 attempt 中存在被舍弃候选而要求重新测量整个 panel

#### Scenario: Invalid selected evidence blocks only the assembly

- **WHEN** selected ref 不存在、跨越来源边界或缺少所需数值
- **THEN** 系统返回定位到该 ref 的结构化错误
- **AND** 系统不自动重测、不发布结果，模型可以修正 decision 或改用其他证据

### Requirement: Gate failures provide a bounded recovery action

证据选择或组装校验失败 SHALL 返回有界的原因、证据位置、当前 panel 和可供主 Agent 选择的下一步动作。下一步动作可以是补充观察、局部重测、舍弃候选、改用视觉证据或放弃无法解决的字段；系统不得要求模型猜测缺失数据，也不得由门禁自动执行动作。

#### Scenario: Evidence issue requests targeted observation

- **WHEN** 当前候选的基准线、文字、系列关系或局部几何仍不确定
- **THEN** 结果指出相关 ref/字段和可用的 `observation_scope` 或 `measurement_target`
- **AND** 主 Agent 可以自主选择是否继续观察

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 主 Agent 选择不再补充证据，或补充证据仍不能解决关键字段
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用未确认的测量候选自动替代模型的最终语义判断

### Requirement: Direct visual assembly remains compatible

对于没有采用测量证据、且模型直接基于清晰源图视觉理解组装合法 ChartSpec 的请求，系统 SHALL 保持直接装配路径。即使当前 run 曾经产生未采用的 observation，模型仍可明确放弃该 observation 后直接组装；该路径不得绕过 ChartSpec 结构校验和后续生成审核。

#### Scenario: No measurement evidence is required

- **WHEN** 模型没有引用任何测量工具结果而提交合法 ChartSpec
- **THEN** 系统按照直接视觉路径完成结构装配
- **AND** 不要求调用方伪造 measurement attempt

#### Scenario: A measured observation can be abandoned

- **WHEN** 模型判断已有测量结果不适用于当前图表语义
- **THEN** 模型可以提交 abandoned observation 或不提供 measurement provenance
- **AND** 系统保留该 observation 的历史记录但不阻塞直接装配
