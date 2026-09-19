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
