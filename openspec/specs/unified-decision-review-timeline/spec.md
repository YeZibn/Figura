# unified-decision-review-timeline Specification

## Purpose

为图表 Agent 建立一条可重建、可展开且跨普通运行与评测运行复用的决策时间线，统一表达观察、模型决策、工具动作、审核门禁、修复和发布，而不替换原始执行事件或削弱模型的证据选择权。

## Requirements

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

系统 SHALL 从同一份有序、持久化的 execution events 生成两种确定性投影：用于关联、状态、重放和 lineage 的内部 decision/process projection，以及用于普通运行和评测展示的用户时间线 projection。系统 SHALL 不把独立且可能漂移的 timeline 文件作为事实来源；相同的事件集合和协议版本 SHALL 产生等价的内部关联、用户可见步骤、状态和顺序。用户时间线不得把 process、turn、operation 或 legacy 关联直接当作可见的业务容器。

#### Scenario: Ordinary and evaluation views use one projection

- **WHEN** 普通会话和评测 case 引用同一 run event history
- **THEN** 两个界面使用相同的用户时间线步骤、工具合并规则、状态标签、错误摘要和展开内容
- **AND** 评测工作台不会重新解释或压缩普通运行已经保存的审核事件

#### Scenario: Timeline rebuilds after reload

- **WHEN** 用户刷新页面或重新打开一个已完成、失败或中断的 run
- **THEN** 客户端可以从历史事件重新得到相同的内部关联和用户时间线
- **AND** 重建不会重新调用模型、工具、审核或发布动作

#### Scenario: Technical lifecycle events are retained but not presented

- **WHEN** history contains model-start、model-completion、operation-save 或 run lifecycle 事件
- **THEN** 这些事件继续作为事实来源参与状态和失败判断
- **AND** 默认用户时间线只显示由它们支持的可读状态、业务步骤或终态错误，不显示技术事件本身

### Requirement: One candidate attempt has one visible review cycle

系统 SHALL 为每个 candidate attempt 建立一个 review cycle。内部 deterministic audit、semantic VLM review、状态更新和修复分类 SHALL 保持可追踪，但默认用户时间线 SHALL 只显示一次“开始审核”和一个最终审核结果；失败结果 SHALL 展示简体中文原因，内部 subcheck 不作为独立可见步骤。

#### Scenario: Candidate review is summarized once

- **WHEN** 候选执行确定性检查和语义 VLM 审核
- **THEN** 时间线显示一个审核周期
- **AND** 用户看到审核开始、最终通过或失败结果及失败原因
- **AND** 不显示多个英文 subcheck

#### Scenario: Collection children share a review parent

- **WHEN** 一次 render 返回同一 collection 的多个 generated child charts
- **THEN** 时间线显示一个 collection review parent 和每个 child 的结果
- **AND** child 数量不会被误显示为多个无关的生成流程

### Requirement: Timeline preserves raw evidence and decision lineage

系统 SHALL 在内部 execution trace 和评测详情中保留工具调用、工具结果、图片、evidence refs、attempt、审核问题、修复结果和历史 decision 事件。默认用户时间线 SHALL 聚焦工具过程、生成候选和审核结果，不显示 measurement decision、focus transition、model turn 或 operation save 等控制事件；隐藏不得删除原始 sequence、call_id、lineage 或安全资源引用。

#### Scenario: Evidence use remains auditable without a visible decision card

- **WHEN** Agent使用一次 measurement observation 中的部分 refs 完成装配
- **THEN** 内部 trace 可以关联 observation、实际使用 refs 和 assemble
- **AND** 默认时间线不创建“测量决策”步骤或待处理卡片

#### Scenario: Detail is unavailable

- **WHEN** 原始工具结果因历史保留、大小或权限原因不可完整读取
- **THEN** 时间线保留工具或审核步骤并显示 detail unavailable/truncated 原因
- **AND** 不伪造内容或成功状态

### Requirement: Runtime facts do not become visible decision gates

内部运行状态 MAY 记录 scope、issues、repair hint、预算和下一次实际动作，但默认前端 SHALL NOT 将这些状态投影为要求用户或模型关闭的 measurement decision unit。只有工具执行、候选生成、最终审核和终态错误形成普通用户可见步骤。

#### Scenario: Measurement warning remains inside the tool result

- **WHEN** 测量返回 warning 或局部补充建议
- **THEN** 用户可在测量工具结果中查看该信息
- **AND** 时间线不额外显示 measurement decision pending

#### Scenario: Review failure remains actionable and concise

- **WHEN** 生成审核失败
- **THEN** 时间线显示审核失败和原因
- **AND** 模型后续选择的实际工具调用按正常工具步骤展示

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

### Requirement: Runtime lifecycle events use a bounded compatibility projection

时间线投影 SHALL 按以下优先级处理没有完整 decision-unit 关联的运行事件：先使用既有 `unit_id`，再使用同一 run 内可验证的 process、turn 或 operation 关联，最后将无法安全关联的事件收敛到有界的 legacy/process 容器。系统不得为每一个未关联事件创建独立的顶层 decision unit，也不得根据缺失字段猜测业务父子关系。

#### Scenario: Real run lifecycle events are grouped

- **WHEN** 一个 run 产生 `run_started`、model lifecycle、operation completed 和 terminal events，但其中部分事件没有 `unit_id`
- **THEN** 时间线将它们按可验证的过程上下文或有限 legacy 容器展示
- **AND** 用户不会看到每个普通生命周期事件各自成为“历史记录（关联不可用）”顶层卡片

#### Scenario: Mixed correlated and legacy events remain separate

- **WHEN** 同一个 run 同时包含有 decision-unit 的 measurement/review 事件和无法关联的生命周期事件
- **THEN** 有 decision-unit 的事件保持原有 unit、phase 和 lineage
- **AND** legacy/process 容器只承载无法安全关联的事件，不把它们错误挂到某个 candidate 或 review

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
