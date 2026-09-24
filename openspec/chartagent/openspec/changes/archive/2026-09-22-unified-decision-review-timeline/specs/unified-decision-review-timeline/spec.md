## Purpose

为图表 Agent 建立一条可重建、可展开且跨普通运行与评测运行复用的决策时间线，统一表达观察、模型决策、工具动作、审核门禁、修复和发布，而不替换原始执行事件或削弱模型的证据选择权。

## ADDED Requirements

### Requirement: Decision units have a canonical bounded identity

系统 SHALL 为一次可解释的测量、生成、审核或发布动作建立有界的 decision unit 关联。关联 SHALL 在适用时包含 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id`、`transition_id` 和下一步状态，并 SHALL 继续保留现有 run、candidate、attempt、scope 和 evidence 引用。

#### Scenario: Measurement and generation remain distinguishable

- **WHEN** 一个 run 先完成测量证据决策，再生成并审核候选图
- **THEN** 时间线可以将测量 unit、生成 candidate attempt 和 review cycle 关联到同一 run
- **AND** 工具观察、Agent 决策、VLM 审核和 publication status 不会被合并成一个无类型的成功事件

#### Scenario: Legacy event remains readable

- **WHEN** 历史事件没有新的 unit 或 transition 字段
- **THEN** 系统将其放入有界的 `legacy/unknown` 单元
- **AND** 不根据缺失字段猜测父子关系、审核通过或发布成功

### Requirement: Timeline projection is derived from canonical execution events

系统 SHALL 从同一份有序、持久化的 execution events 生成普通运行和评测运行的时间线投影。系统 SHALL 不把独立且可能漂移的 timeline 文件作为事实来源；相同的事件集合和协议版本 SHALL 产生等价的分组、状态和顺序。

#### Scenario: Ordinary and evaluation views use one projection

- **WHEN** 普通会话和评测 case 引用同一 run event history
- **THEN** 两个界面使用相同的 unit 分组、阶段顺序、状态标签和展开内容
- **AND** 评测工作台不会重新解释或压缩普通运行已经保存的审核事件

#### Scenario: Timeline rebuilds after reload

- **WHEN** 用户刷新页面或重新打开一个已完成、失败或中断的 run
- **THEN** 客户端可以从历史事件重新得到相同的时间线
- **AND** 重建不会重新调用模型、工具、审核或发布动作

### Requirement: Each decision unit exposes a closed next-action contract

存在待完成动作的 unit SHALL 暴露当前阶段、状态、是否必需、允许的下一动作和禁止的越界动作。`applied`、`selected`、`reviewing` 等中间状态 SHALL 不能单独被解释为该 unit 已完成。

#### Scenario: Focus application remains pending until observation

- **WHEN** 局部测量范围已经应用但尚未返回该范围的 measurement observation
- **THEN** 时间线将该 unit 标记为待观察并显示允许的同范围测量或显式放弃动作
- **AND** 不显示为已获得有效证据

#### Scenario: Terminal decision closes the unit

- **WHEN** Agent 明确放弃证据、审核进入 terminal 或 publication 被拒绝
- **THEN** unit 显示终态、原因和不可继续的动作
- **AND** 主链路不得把该 unit 当作成功完成

### Requirement: One candidate attempt has one visible review cycle

系统 SHALL 为每个 candidate attempt 建立一个 review cycle，并在该 cycle 内区分 deterministic quality audit、tool-free semantic VLM review、repair decision 和最终 review state。shared gate 状态更新、tool result 中的 review snapshot 和子检查结果 SHALL 不再各自产生新的顶层审核周期。

#### Scenario: Candidate review has multiple sub-checks

- **WHEN** 一个候选先执行确定性质量检查，再执行语义 VLM 审核
- **THEN** 时间线显示一个 review cycle 和两个可展开的子检查
- **AND** 用户不会看到两个或多个相互竞争的“审核开始”事件

#### Scenario: Collection children share a review parent

- **WHEN** 一次 render 返回同一 collection 的多个 generated child charts
- **THEN** 时间线显示一个 collection review parent 和每个 child 的结果
- **AND** child 数量不会被误显示为多个无关的生成流程

### Requirement: Timeline preserves raw evidence and decision lineage

时间线 SHALL 允许用户从一个摘要 unit 展开到关联的工具调用、工具结果、图片、evidence refs、Agent decision、审核问题和修复结果。摘要和聚合 SHALL 不覆盖或删除原始事件的 sequence、call_id、attempt 和安全资源引用。

#### Scenario: Evidence selection is inspectable

- **WHEN** Agent 从一次 measurement observation 中选择部分 refs 并舍弃其他 refs
- **THEN** 时间线在同一 measurement unit 下同时显示 observation、selected/discarded decision 和后续 assemble
- **AND** 用户可以定位该决策对应的 attempt 和 scope

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可完整读取
- **THEN** 时间线保留 unit 身份和状态并显示明确的 detail unavailable/truncated 原因
- **AND** 不伪造缺失的证据或把 unit 标记为成功

### Requirement: Timeline transitions are idempotent and lineage-safe

相同 run、unit、attempt、phase 和 transition 的重复事件 SHALL 只产生一个可见状态转换。修复或重试产生新 attempt 时 SHALL 保留父 unit 和失败原因；旧 attempt 不得被覆盖为新 attempt 的状态。

#### Scenario: Duplicate review snapshot is replayed

- **WHEN** shared review 更新和 tool result snapshot 描述同一个 candidate review transition
- **THEN** 时间线只显示一次对应的状态转换
- **AND** 原始事件仍可在展开详情中按 sequence 查看

#### Scenario: Repair creates a new attempt

- **WHEN** evidence-needed 或 spec-only 修复重新组装并渲染候选
- **THEN** 新 attempt 关联父 attempt 和 repair kind
- **AND** 父 attempt 的失败、证据和不可发布状态保持可读
