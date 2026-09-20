# measurement-quality-gate Specification

## Purpose

为图表测量建立可追踪、可审计且不可被静默越过的证据生命周期，使初次测量结果在进入结构化图表数据前经过明确的质量判断，并为后续定向重测保留稳定的上下文和 lineage。

## Requirements

### Requirement: Measurement evidence has an explicit lifecycle

系统 SHALL 为每次源图测量提供明确的生命周期状态，至少区分 `provisional`、`accepted`、`remeasure_required`、`partial`、`unsupported` 和 `failed`。初次测量 SHALL 默认作为候选证据，除非通过适用的质量检查，否则不得被视为确定性事实。

#### Scenario: Initial measurement remains provisional

- **WHEN** 柱状图、折线图、饼图或散点图传感器完成一次测量
- **THEN** 结果包含有界的测量状态、confidence、warnings 和结构化质量信息
- **AND** 未经接受的结果不得被下游默认为已经确认的源图数值

#### Scenario: Blocking uncertainty requires remeasurement

- **WHEN** 测量发现基准线、坐标标定、系列关联、覆盖范围或几何支持存在阻断性问题
- **THEN** 结果状态为 `remeasure_required`、`partial`、`unsupported` 或 `failed` 中适用的一项
- **AND** 结果包含定位到具体证据区域的结构化问题

### Requirement: Measurement attempts remain attributable

系统 SHALL 按精确的源附件和面板身份维护测量会话，并 SHALL 为每次测量记录稳定的 attempt 身份、父 attempt、工具、测量范围、质量结果和来源证据引用。重复调用、恢复或重连不得使一个测量结果归属于其他附件或面板。

#### Scenario: Attempts form a recoverable lineage

- **WHEN** 同一 panel 发生初次测量、质量检查或后续重测
- **THEN** 每次结果可以通过 session、attempt 和父 attempt 关联到同一 `attachment_id + panel_id`
- **AND** 下游可以识别当前采用的 attempt 与被淘汰或未决的 attempt

#### Scenario: Persisted context does not cross panel boundaries

- **WHEN** Agent 从 checkpoint 或历史状态恢复测量上下文
- **THEN** 只恢复与当前附件和面板匹配的测量会话
- **AND** 不得把其他 panel 的 accepted 或 provisional 证据用于当前 ChartSpec

### Requirement: Quality audit returns structured measurement issues

每次测量 SHALL 经过适用的质量审计，并 SHALL 以结构化方式报告范围、几何、标定、覆盖、关联和可视证据完整性。审计不得把低置信度结果静默提升为成功，也不得因不确定性丢弃仍可检查的部分像素证据。

#### Scenario: Material geometry uncertainty is blocking

- **WHEN** 柱状图基准线残差过大、折线坐标标定不足、饼图扇区总和不一致或散点存在无法解析的关键重叠
- **THEN** 审计结果包含对应 issue code、location、severity 和 bounded message
- **AND** 结果不能被标记为无条件 accepted

#### Scenario: Partial evidence remains inspectable

- **WHEN** 测量只能确认部分柱体、轨迹、扇区或散点
- **THEN** 系统保留已确认的结构化像素证据和 overlay
- **AND** 未确认部分保持 null、partial 或 unresolved，不得被补成确定数值

### Requirement: Measurement quality state is bounded and serializable

测量状态、质量检查、问题、范围和 attempt lineage SHALL 使用有界、可序列化的结果表达，并 SHALL 能够在 Agent observation、run artifact index、checkpoint 和恢复流程之间保持一致。结果不得暴露本地路径、图像字节或 provider 原始 payload。

#### Scenario: Observation and recovery preserve the same quality state

- **WHEN** 测量结果通过工具观察返回后被写入运行记录并在后续恢复
- **THEN** 恢复后的状态、accepted attempt、未解决问题和来源身份与原结果一致
- **AND** 恢复不会把 provisional 或 failed 结果升级为 accepted

### Requirement: Measurement issues expose machine-readable repair targets

当测量质量审计发现需要补充证据的问题时，系统 SHALL 返回有界的 repair action 和 measurement target。target 至少能够表达当前 `attachment_id`、`panel_id`、父 attempt、目标区域或证据位置、受影响字段以及建议的测量工具；缺少可靠区域时 SHALL 明确表示需要 panel 级复查，而不得伪造精确框选。

#### Scenario: Baseline issue identifies a bounded target

- **WHEN** 柱状图测量因零基线残差或基准线冲突进入 `remeasure_required`
- **THEN** 质量结果包含指向当前 panel 和 baseline 字段的 repair action
- **AND** 如果源图坐标足够可靠，target 包含有界的源图区域和父 attempt 引用

#### Scenario: Repair target cannot cross panel boundaries

- **WHEN** 模型提交的 repair target 不属于当前 measurement session 的 attachment 或 panel
- **THEN** 系统拒绝该 target 并返回结构化来源不匹配问题
- **AND** 不创建新的可接受 measurement attempt

### Requirement: Remeasurement attempts are bounded and re-audited

每次定向重测 SHALL 在同一 run、attachment 和 panel 的 measurement session 中创建新的 attempt，并记录父 attempt、target 和修复原因。重测结果 SHALL 重新经过质量审计；重复的等价请求 SHALL 幂等，且超过有界预算时 SHALL 保留明确的非接受状态。

#### Scenario: A corrected local attempt can become accepted

- **WHEN** 当前 panel 的定向重测解决了父 attempt 的阻断 issue，且视觉证据、作用域和图表专属检查均通过
- **THEN** 新 attempt 被标记为 `accepted`
- **AND** `assemble_spec` 只能引用该新 attempt，而不能继续使用未接受的父 attempt

#### Scenario: Repair budget is exhausted

- **WHEN** 同一 panel 的重测次数达到配置上限，或同一 target 被重复拒绝
- **THEN** session 返回 `failed`、`partial` 或 `remeasure_required` 中适用的终态
- **AND** Agent 保留问题、attempt lineage 和可恢复上下文，不发布未经接受的 ChartSpec

### Requirement: Measurement review is a hard gate for the main chain

测量质量审核 SHALL 在测量结果提交后成为当前 run 和 panel 的主链路门禁，而不只在 `assemble_spec` 引用时做最后校验。未通过审核的测量不得用于 assemble、生成图或最终成功结论。

#### Scenario: Measurement audit blocks assembly
- **WHEN** 一次测量返回 `provisional`、`remeasure_required`、`partial`、`unsupported` 或 `failed`
- **THEN** 系统阻止依赖该测量的 assemble 和后续生成阶段
- **AND** `assemble_spec` 的引用校验继续作为防御性校验保留

#### Scenario: A failed measurement stops the current tool batch
- **WHEN** 模型一次返回多个工具调用，且其中一次测量审核产生阻断问题
- **THEN** 当前测量之后尚未开始的无关调用不得执行
- **AND** 它们被记录为未开始，并由审核修复流程重新决定是否执行

#### Scenario: Only the approved repair may run
- **WHEN** 测量审核提供同一 panel 内的定向重测 target
- **THEN** 系统只允许匹配 attachment、panel、父 attempt 和 target 的重测
- **AND** 新 attempt 重新审核并通过后，门禁才释放

#### Scenario: Measurement exhaustion prevents chart output
- **WHEN** 定向重测失败或达到预算上限
- **THEN** 当前 run 保留 attempt lineage、问题和恢复信息
- **AND** 系统不得组装或发布基于未接受测量的 ChartSpec
