## MODIFIED Requirements

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
- **AND** 工具观察、Agent 决策、审核和 publication status 不会被合并成一个无类型的成功事件

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

- **WHEN** history contains model-start、model-completion、operation-save 或原始审核事件
- **THEN** 这些事件继续作为事实来源参与状态和失败判断，并保留在技术详情中
- **AND** 默认用户时间线只显示统一节点的中文标题、阶段、状态和业务结果

### Requirement: One candidate attempt has one visible review cycle

系统 SHALL 为每个 candidate attempt 建立一个 canonical review cycle，并且整个
cycle 只能使用一个 review identity。内部 deterministic audit、semantic VLM
review、状态更新和修复分类 SHALL 保持可追踪，但不得生成第二套
`chart_review_*` 生命周期事件。默认用户时间线 SHALL 只显示审核中状态和一个
最终审核结果；失败结果 SHALL 展示简体中文原因，内部 subcheck 不作为独立可见步骤。

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

系统 SHALL 在内部 execution trace 和评测详情中保留工具调用、工具结果、图片、
evidence refs、attempt、审核问题、修复结果和历史 decision 事件。默认用户时间线
SHALL 聚焦工具过程、生成候选和审核结果，不显示 measurement decision、focus
transition、model turn、operation save 或内部 review subcheck 等控制事件；隐藏不得
删除原始 sequence、call_id、lineage 或安全资源引用。

#### Scenario: Evidence use remains auditable without a visible decision card

- **WHEN** Agent 使用一次 measurement observation 中的部分 refs 完成装配
- **THEN** 内部 trace 可以关联 observation、实际使用 refs 和 assemble
- **AND** 默认时间线不创建“测量决策”步骤或待处理卡片

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可完整读取
- **THEN** 时间线保留对应节点并显示 detail unavailable/truncated 原因
- **AND** 不伪造内容或成功状态

## REMOVED Requirements

### Requirement: Runtime lifecycle events use a bounded compatibility projection

**Reason**: 新协议要求所有进入时间线的事件具有完整语义关联；legacy/unknown 容器和客户端猜测会重新引入英文、重复步骤和错误完成状态。

**Migration**: 清理旧事件夹具和旧评测记录，使用新的严格事件生产协议重新生成运行历史；不提供运行时兼容读取路径。
