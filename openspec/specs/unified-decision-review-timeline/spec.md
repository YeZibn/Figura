# unified-decision-review-timeline Specification

## Purpose

为图表 Agent 建立一条可重建、可展开且跨普通运行与评测运行复用的决策时间线，统一表达观察、模型决策、工具动作、审核门禁、修复和发布，而不替换原始执行事件或削弱模型的证据选择权。

## Requirements

### Requirement: Decision units have a canonical bounded identity

系统 SHALL 为一次可解释的测量、生成、审核或发布动作建立唯一且完整的
decision unit 关联。关联 SHALL 在适用时包含 `unit_id`、`unit_type`、
`phase`、`actor`、`role`、`parent_unit_id`、`transition_id` 和状态，并 SHALL
继续保留现有 run、candidate、attempt、scope 和 evidence 引用。新的运行事件
不得使用 `legacy` 或 `unknown` unit；缺少必填关联字段的事件必须在协议边界
失败，而不是由客户端猜测父子关系或创建兜底容器。

#### Scenario: Measurement and generation remain distinguishable

- **WHEN** 一个 run 先完成测量证据决策，再生成并审核候选图
- **THEN** 时间线可以将测量 unit、生成 candidate attempt 和 review cycle 关联到同一 run
- **AND** 工具观察、Agent 决策、VLM 审核和 publication status 不会被合并成一个无类型的成功事件

#### Scenario: Every visible unit is fully classified

- **WHEN** 客户端重建新的运行事件
- **THEN** 每个可见 unit 都具有确定的类型、阶段、角色和状态
- **AND** 客户端不会显示“未分类记录”“历史事件（兼容模式）”或“状态未知”

### Requirement: Timeline projection is derived from canonical execution events

系统 SHALL 从同一份有序、持久化的 execution events 生成一个确定性的时间线
投影，普通运行和评测运行 SHALL 复用该投影。该投影 SHALL 以一个统一的
时间线节点模型承载工具调用、工具结果、视觉观察、生成候选、审核结果和
发布状态；不得再维护互相独立且可能产生不同状态的 ToolStep 与 DecisionUnit
用户投影。技术生命周期事件可以参与节点状态归约，但默认用户时间线只显示
可读业务步骤和终态错误。

#### Scenario: Ordinary and evaluation views use one projection

- **WHEN** 普通会话和评测 case 引用同一 run event history
- **THEN** 两个界面使用相同的用户时间线步骤、工具合并规则、状态标签、错误摘要和展开内容
- **AND** 评测工作台不会重新解释或压缩普通运行已经保存的审核事件

#### Scenario: Tool status is promoted by the authoritative result

- **WHEN** 一个生成或测量工具先产生调用事件，随后产生 `tool_result.success`
- **THEN** 对应时间线节点从运行中变为已完成
- **AND** 不会同时保留一个“状态未知”的生成节点

#### Scenario: Timeline rebuilds after reload

- **WHEN** 用户刷新页面或重新打开一个已完成、失败或中断的 run
- **THEN** 客户端可以从历史事件重新得到相同的内部关联和用户时间线
- **AND** 重建不会重新调用模型、工具、审核或发布动作

#### Scenario: Technical lifecycle events are retained but not presented

- **WHEN** history contains model-start、model-completion、operation-save 或 run lifecycle 事件
- **THEN** 这些事件继续作为事实来源参与状态和失败判断，并保留在技术详情中
- **AND** 默认用户时间线只显示统一节点的中文标题、阶段、状态和业务结果

### Requirement: One candidate attempt has one visible review cycle

系统 SHALL 为每个 candidate attempt 建立一个 canonical review cycle，并且整个
cycle 只能使用一个 review identity。内部 deterministic audit、semantic VLM
review、状态更新和修复分类 SHALL 保持可追踪，但不得生成第二套
`chart_review_*` 生命周期事件。默认用户时间线 SHALL 只显示审核中状态和一个
最终审核结果；失败结果 SHALL 展示简体中文原因，内部 subcheck 不作为独立可见
步骤。

#### Scenario: Candidate review is summarized once

- **WHEN** 候选执行确定性检查和语义 VLM 审核
- **THEN** 时间线显示一个审核周期及其最终通过或失败结果
- **AND** 用户看不到多个英文 review kind 或重复审核卡片

#### Scenario: Review identity remains stable

- **WHEN** 同一 candidate attempt 的内部检查、审核快照和发布结果陆续到达
- **THEN** 它们都关联到同一个 review identity
- **AND** 内部检查不会创建新的顶层 review unit

#### Scenario: Collection children share a review parent

- **WHEN** 一次 render 返回同一 collection 的多个 generated child charts
- **THEN** 时间线显示一个 collection review parent 和每个 child 的结果
- **AND** child 数量不会被误显示为多个无关的生成流程

### Requirement: Timeline preserves raw evidence and decision lineage

系统 SHALL 在可用的内部 execution trace 和评测详情中保留工具调用、工具结果、图片引用、measurement/evidence refs、attempt、scope、质量诊断、审核问题、修复结果及实际 assembly 引用。默认用户时间线 SHALL 聚焦工具过程、生成候选和审核结果；measurement 候选使用与否从实际 assembly 输入读取，不生成独立 measurement decision 事件或待处理卡片。

#### Scenario: Evidence use remains auditable without a decision event

- **WHEN** Agent 使用一次 measurement observation 中的部分 refs 完成装配
- **THEN** 内部 trace 可以关联 observation、实际 assembly refs 和生成结果
- **AND** 默认时间线不创建“测量决策”、选择/舍弃或待处理步骤

#### Scenario: Measurement result remains inspectable when unused

- **WHEN** 某次 measurement observation 未被后续 assembly 引用
- **THEN** 可用的工具结果仍可按普通运行详情查看
- **AND** 不推导 abandoned、discarded 或未完成的 measurement 状态

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可完整读取
- **THEN** 时间线保留工具或审核步骤并显示 detail unavailable/truncated 原因
- **AND** 不伪造内容或成功状态

### Requirement: Runtime facts do not become visible decision gates

measurement scope、issues、质量信息和模型后续实际选择 SHALL 作为工具结果及实际工具调用中的事实呈现。默认前端 SHALL NOT 将 measurement decision、repair queue、focus transition 或 evidence selection/discard 投影为要求模型关闭的状态单元；只有工具执行、候选生成、generated-chart review 和终态错误形成对应时间线步骤。

#### Scenario: Measurement warning remains inside the tool result

- **WHEN** 测量返回 warning 或局部补充线索
- **THEN** 用户可在测量工具结果中查看该信息
- **AND** 时间线不额外显示 measurement decision pending 或自动重测步骤

#### Scenario: Review failure remains actionable and concise

- **WHEN** 生成审核失败
- **THEN** 时间线显示审核失败和原因
- **AND** 模型后续选择的实际工具调用按正常工具步骤展示

#### Scenario: Model-selected local retest appears as a normal tool call

- **WHEN** 主 Agent 根据不确定性显式再次调用带 scope/target 的测量工具
- **THEN** 时间线展示这次新的测量工具调用和结果
- **AND** 不将其重包装成 repair queue 或 evidence decision 生命周期

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

### Requirement: Projected failures preserve actionable error context

时间线投影 SHALL 保留错误类别、稳定错误码、provider 状态（如存在）、安全的用户可读原因、是否可重试以及第一失败事件引用。摘要可以截断正文，但不得只保留无上下文的通用“运行失败”文本。

#### Scenario: Provider rejection remains diagnosable

- **WHEN** provider 返回确定性的拒绝并导致 run 终止
- **THEN** 时间线显示 provider 拒绝类别、状态或错误码和脱敏后的原因
- **AND** 用户可以区分它与远端结果未知的网络或超时失败

#### Scenario: Replay does not lose failure details

- **WHEN** 用户刷新、重连或在评测工作台读取同一 run 的历史事件
- **THEN** 投影仍显示相同的错误类别、原因和失败引用
- **AND** 重建不会重新调用 provider 或创建新的 decision unit
