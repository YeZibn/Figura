## MODIFIED Requirements

### Requirement: Model-led evidence planning

对于需要恢复结构化图表数据的请求，系统 SHALL 允许多模态模型先基于源图像形成初步语义理解，并根据具体不确定点选择 OCR、图表几何观测或布局观测工具。系统 SHALL NOT 要求所有图表遵循固定的 inspect、传感器、装配顺序；当模型拥有足够的视觉证据时，模型 SHALL 可以直接请求 `assemble_spec`。当已有测量结果存在局部不确定性时，模型 SHALL 可以再次调用相同图表测量工具并提供 bounded `measurement_target`；系统不得自动替模型发起重测。

#### Scenario: Clear chart is assembled directly

- **WHEN** 用户提供清晰且语义完整的图表并要求恢复数据
- **THEN** 模型可以基于多模态视觉理解直接请求 `assemble_spec`
- **AND** 系统不因未调用 `inspect_chart_layout` 或某个图表传感器而拒绝该流程

#### Scenario: Uncertainty selects a targeted observer

- **WHEN** 模型能够判断图表语义但无法可靠读取文字、数值、坐标轴或图形几何中的一个局部
- **THEN** 模型可以只调用与该不确定点对应的 OCR、图表几何或布局工具
- **AND** 对已有图表测量结果的局部补充 SHALL 通过同一测量工具的 `measurement_target` 完成

#### Scenario: Measurement warning does not force a retry

- **WHEN** 工具返回 warning、候选冲突或低置信度结果
- **THEN** 模型可以接受、舍弃候选或主动请求局部补充证据
- **AND** 系统不得因为 warning 自动重复相同的全量测量

#### Scenario: Descriptive question stays lightweight

- **WHEN** 用户只询问图表趋势、组成或其他不需要结构化数据的问题
- **THEN** 模型可以直接回答或调用必要的视觉辅助工具
- **AND** 系统不要求调用 `assemble_spec` 或完成完整的图表恢复链路

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

### Requirement: Measurement evidence must pass an acceptance gate before assembly

当 ChartSpec 数据来自图表测量工具时，证据融合流程 SHALL 在 `assemble_spec` 之前确认对应的 measurement session 存在可归属的 attempt，并确认主 Agent 已明确选择所引用的证据。provisional、remeasure_required、partial、unsupported 或 failed 的测量结果不得被静默当作确定性源值。该确认 SHALL 由主 Agent 的主链路决策和代码侧硬性校验共同完成，不要求额外的语义审核工具。

#### Scenario: Unaccepted bar measurement blocks assembly

- **WHEN** 模型使用带有基准线不确定 warning 的柱状图测量结果请求组装 ChartSpec，但没有提交可接受的证据选择
- **THEN** 系统返回定位到测量会话和具体问题的结构化门禁错误
- **AND** 不返回可被当作已确认数据的 ChartSpec，也不自动重测

#### Scenario: Accepted evidence permits assembly

- **WHEN** 当前 attachment 和 panel 的测量 attempt 已通过适用的硬性检查，并且主 Agent 选择了对应证据引用
- **THEN** 模型可以将该证据用于 `assemble_spec`
- **AND** 生成的 ChartSpec 保留已接受测量的来源摘要或引用

### Requirement: Gate failures provide a bounded recovery action

测量门禁失败 SHALL 返回有界的原因、证据位置和可供主 Agent 选择的下一步动作。下一步动作可以是补充观测、通过原测量工具请求局部重测、保留不确定值或放弃无法解决的字段，但不得要求模型猜测缺失数据，也不得由门禁自动执行动作。

#### Scenario: Baseline issue offers focused observation

- **WHEN** 柱状图测量因基准线残差或基准线冲突未被接受
- **THEN** 门禁结果指出 baseline issue、相关证据引用和可用的定向观察范围
- **AND** 主 Agent 可以根据该信息主动调用带 `measurement_target` 的原柱状图工具

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 主 Agent 选择不再补充证据，或定向补充证据仍不能解决关键字段
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用模型猜值替代 accepted measurement evidence

### Requirement: Measurement gate failures drive targeted evidence recovery

当 `assemble_spec` 因 measurement evidence 未被接受而阻断时，系统 SHALL 返回当前 panel/source 身份、受影响字段、证据引用和可选的父 attempt 上下文。主 Agent 可以据此在同一主链路中请求当前 panel 的定向补充证据，但系统不得自动切换 panel、自动重测或直接发布结果。

#### Scenario: Blocked assembly requests a targeted remeasurement

- **WHEN** 当前柱状图 attempt 因 baseline issue 未通过 measurement gate
- **THEN** 组装结果包含指向 baseline 或相关 bar region 的有界 focus suggestion
- **AND** 主 Agent 可以继续当前 run 的证据闭环并调用原测量工具，而不是直接结束为成功或发布结果

#### Scenario: Unrecoverable evidence remains non-final

- **WHEN** 定向补充证据仍不能解决关键字段，或 target budget 已耗尽
- **THEN** 融合结果保留未解析字段、问题和 attempt lineage
- **AND** 系统不得用模型猜值替代 accepted measurement evidence

## ADDED Requirements

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
