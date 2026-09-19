# chart-evidence-fusion Specification

## Purpose

让多模态模型负责图表语义理解与最终装配，让 OCR、几何 CV 和布局观测按需提供可追溯证据，并在证据冲突时保留不确定性而不是静默猜测。

## Requirements

### Requirement: Model-led evidence planning

对于需要恢复结构化图表数据的请求，系统 SHALL 允许多模态模型先基于源图像形成初步语义理解，并根据具体不确定点选择 OCR、图表几何观测或布局观测工具。系统 SHALL NOT 要求所有图表遵循固定的 inspect、传感器、装配顺序；当模型拥有足够的视觉证据时，模型 SHALL 可以直接请求 `assemble_spec`。

#### Scenario: Clear chart is assembled directly

- **WHEN** 用户提供清晰且语义完整的图表并要求恢复数据
- **THEN** 模型可以基于多模态视觉理解直接请求 `assemble_spec`
- **AND** 系统不因未调用 `inspect_chart_layout` 或某个图表传感器而拒绝该流程

#### Scenario: Uncertainty selects a targeted observer

- **WHEN** 模型能够判断图表语义但无法可靠读取文字、数值、坐标轴或图形几何中的一个局部
- **THEN** 模型可以只调用与该不确定点对应的 OCR、CV 或布局工具
- **AND** 工具调用顺序可以根据当前证据动态调整

#### Scenario: Descriptive question stays lightweight

- **WHEN** 用户只询问图表趋势、组成或其他不需要结构化数据的问题
- **THEN** 模型可以直接回答或调用必要的视觉辅助工具
- **AND** 系统不要求调用 `assemble_spec` 或完成完整的图表恢复链路

### Requirement: Chart observations are attributable evidence

OCR、图表几何传感器和布局观测 SHALL 向模型返回可区分的证据类型、来源、置信度、警告和结构化结果；当工具产生有效的源图像 overlay 时，系统 SHALL 按现有多模态观测协议把它与结构化结果关联返回。工具结果 SHALL 表示观测和候选值，不得把单个工具结果无条件标记为源图像的最终真值。

#### Scenario: OCR and geometry evidence remain distinguishable

- **WHEN** 模型分别调用 OCR 和柱状图或折线图传感器
- **THEN** 下一轮模型上下文能够区分文字证据与几何证据的来源、置信度和警告
- **AND** 每类证据仍保留其适用的像素位置或源图像关联

#### Scenario: Visual evidence remains linked to its observation

- **WHEN** 图表传感器返回结构化数据和源尺寸 overlay
- **THEN** 模型可以将 overlay 与对应工具调用和结构化结果关联起来
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

### Requirement: Measurement evidence must pass an acceptance gate before assembly

当 ChartSpec 数据来自图表测量工具时，证据融合流程 SHALL 在 `assemble_spec` 之前确认对应的 measurement session 存在可归属的 accepted attempt。provisional、remeasure_required、partial、unsupported 或 failed 的测量结果不得被静默当作确定性源值。

#### Scenario: Unaccepted bar measurement blocks assembly

- **WHEN** 模型使用带有基准线不确定 warning 的柱状图测量结果请求组装 ChartSpec
- **THEN** 系统返回定位到测量会话和具体问题的结构化门禁错误
- **AND** 不返回可被当作已确认数据的 ChartSpec

#### Scenario: Accepted evidence permits assembly

- **WHEN** 当前 attachment 和 panel 的测量 attempt 已通过适用的质量检查并标记为 accepted
- **THEN** 模型可以将该证据用于 `assemble_spec`
- **AND** 生成的 ChartSpec 保留已接受测量的来源摘要或引用

### Requirement: Gate failures provide a bounded recovery action

测量门禁失败 SHALL 返回有界的原因、证据位置和下一步动作。下一步动作可以是补充观测、重新测量、保留不确定值或放弃无法解决的字段，但不得要求模型猜测缺失数据。

#### Scenario: Baseline issue requests further observation

- **WHEN** 柱状图测量因基准线残差或基准线冲突未被接受
- **THEN** 门禁结果指出 baseline issue 和可用的复查动作
- **AND** Agent 可以基于该动作继续当前 panel 的证据闭环，而不是直接生成图表

### Requirement: Direct visual assembly remains compatible

对于没有调用测量工具、且模型直接基于清晰源图视觉理解组装的请求，系统 SHALL 保持现有直接 `assemble_spec` 兼容路径。该兼容路径不得绕过已经存在的 ChartSpec 结构校验和后续生成审核。

#### Scenario: No measurement session is required for direct visual input

- **WHEN** 模型没有引用任何测量工具结果而提交一个合法的单 ChartSpec
- **THEN** 系统按照现有路径完成结构装配
- **AND** 不要求调用方伪造 measurement attempt
