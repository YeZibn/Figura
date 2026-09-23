## MODIFIED Requirements

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL keep tool execution, measurement evidence, canonical review, and publication status in independent fields. `tool_call`/`tool_result` express measurement invocation and candidate result; new runs SHALL NOT emit separate measurement decision, selection, discard, focus, or repair lifecycle events. Measurement results SHALL NOT be interpreted as generated-chart review outcomes. `review_started` and `review_completed` SHALL be public review lifecycle events; Run lifecycle SHALL distinguish active, completed, failed, interrupted, and history-gap.

#### Scenario: Tool result reports candidate evidence facts

- **WHEN** OCR 或图表测量工具完成
- **THEN** tool result 和适用的 observation 记录独立报告执行状态、scope、refs、质量/系列 metadata 和 overlay
- **AND** 工具成功不会自动产生 accepted、published 或 generated-review-passed 状态

#### Scenario: Actual usage is visible in the assembly request

- **WHEN** 主 Agent 在 assembly 中使用某些 measurement evidence refs
- **THEN** trace 可以通过同一 run 中的实际工具调用和 assembly 输入关联这些 refs
- **AND** 不新增选择、舍弃或待决事件

#### Scenario: Generated review has one authoritative lifecycle

- **WHEN** a generated candidate enters review, repair, or publication
- **THEN** the trace contains one canonical `review_started` transition, one final `review_completed` or `review_failed` transition, and an explicit publication transition when applicable
- **AND** internal deterministic and VLM checks remain diagnostic details rather than parallel review lifecycles

### Requirement: Measurement tool calls are attributable

执行追踪 SHALL 通过实际 measurement tool calls 及其结果保留首次 scope 或后续局部 scope、run/panel/attempt、父 attempt（如适用）、measurement/evidence refs、quality 与必要的结果摘要。局部重测是模型显式发起的下一次普通测量调用，不额外生成 measurement decision、repair-required、repair-rejected、pending-focus 或 repair-budget timeline unit。trace 不得记录原始图片、绝对路径、密钥或 provider 原始 payload。

#### Scenario: A scoped observation is correlated with its panel

- **WHEN** Agent 根据模型提供的 `observation_scope` 发起测量
- **THEN** trace 可关联 scope、panel、attempt、实际应用区域和工具结果
- **AND** 观察范围与候选结果属于同一工具调用

#### Scenario: A local remeasurement is an ordinary tool call

- **WHEN** Agent 根据不确定候选显式调用图表测量工具并提交 `measurement_target`
- **THEN** trace 记录新调用、父 attempt 关联、范围和返回的候选结果
- **AND** 不需要额外的 repair lifecycle 或 evidence selection event

#### Scenario: A local measurement failure remains a tool result

- **WHEN** 定向范围为空、无法应用或质量不足
- **THEN** trace 保留该 tool call 的有界失败/质量诊断
- **AND** 不伪造 pending measurement unit 或将其归类为 generated-chart review failure

### Requirement: Candidate lifecycle events share stable scope correlation

候选生成、measurement tool observation、审核、修复和 publication 事件 SHALL 在适用时共享 `candidate_id`、attempt、source scope 和 repair kind。事件 SHALL 保持工具执行、measurement evidence、chart review 与 publication status 的语义分离；measurement evidence 的是否采用由实际 assembly 输入体现，不形成独立事件种类。

#### Scenario: Measurement and generated review are not displayed as one status

- **WHEN** 一个候选经历 measurement observation、assembly、`review_started` 和 generated-chart rejection
- **THEN** trace 保留各实际工具调用、审核和发布状态
- **AND** 关联字段允许客户端把它们归入同一 candidate attempt，但 measurement 成功不被解释为 review passed

### Requirement: Pending transitions are explicit in the execution trace

执行追踪 SHALL 仅对确实跨越工具调用且会改变运行可恢复性的动作记录 pending/next-action 状态。一次 measurement tool call SHALL 将请求 scope、实际应用范围与 observation 结果作为同一操作的事实；不存在可独立等待的 measurement focus 或 evidence decision transition。审核等其他实际阻塞操作仍可显式记录其当前状态。

#### Scenario: Measurement scope and observation are atomic

- **WHEN** trace 收到一次成功应用 scope 的 measurement tool result
- **THEN** 当前 measurement attempt 同时包含该 effective scope 和 observation refs
- **AND** trace 不留下 pending next action 等待第二个 measurement/evidence-decision 事件

#### Scenario: A failed tool call does not become a pending evidence unit

- **WHEN** 局部测量调用没有产生可用 observation
- **THEN** tool result 保存失败或不充分原因
- **AND** 主 Agent 可在下一轮自主选择重试、调整 scope、使用其他证据或停止，无需先关闭 abandonment unit

## REMOVED Requirements

### Requirement: Measurement repair events have stable client presentation

**Reason**: selected/discarded、repair-required、repair-rejected 和 repair-exhausted 不再是测量候选生命周期事件；保留这些事件契约会迫使 trace 与客户端继续维护已删除的第二套状态。

**Migration**: 新运行用普通 measurement `tool_call`/`tool_result` 展示实际调用和结果。评测与历史投影不再生成这些 measurement repair 事件的用户步骤；生成图审核的 canonical review events 保持不变。

## ADDED Requirements

### Requirement: Measurement tool results have stable client presentation

执行追踪 SHALL 让 measurement 工具调用与结果通过稳定的 `tool_name`、`call_id`、run sequence 和来源/attempt correlation 关联。客户端 SHALL 使用工具目录的中文名称及 bounded result fields 呈现调用和结果，不需要为 measurement 候选选择、舍弃或 repair 建立额外 event kind。

#### Scenario: Measurement call and result share one presentation identity

- **WHEN** 客户端接收 measurement `tool_call` 与 `tool_result`
- **THEN** 两者通过稳定的 `call_id` 合并为一个可展开工具步骤
- **AND** scope、refs、质量信息和 overlay 按授权资源引用读取

#### Scenario: Replay and live delivery share the same presentation

- **WHEN** 同一 measurement tool call/result 通过历史回放和实时/重连流到达
- **THEN** 客户端使用相同的工具名、字段含义和状态解释
- **AND** 按 run 与 sequence 去重，不产生重复工具步骤
