# execution-trace Specification

## Purpose

Make Agent execution inspectable and recoverable across the live run, page reloads, session switches, and Gateway restarts while keeping final answers readable as safe Markdown.

## Requirements

### Requirement: Agent runs have durable execution history

The system SHALL preserve a bounded, ordered execution history for each Agent
run, including lifecycle events, model-turn boundaries, tool calls, tool
results, visual observations, failures, budget termination, and the final
answer when available. The history SHALL retain the event sequence and run
status independently from the model conversation history.

#### Scenario: Completed run history is available after reload

- **WHEN** an Agent run completes and the user reloads the desktop client
- **THEN** the client can retrieve the run's ordered execution history and
  final answer from the Gateway
- **AND** the recovered history contains the same bounded event order without
  requiring the Agent to run again

#### Scenario: Failed run history remains inspectable

- **WHEN** an Agent run fails after producing one or more execution events
- **THEN** the failure state and events produced before failure remain
  available for inspection
- **AND** the history does not claim a successful final answer

#### Scenario: Event history is bounded and sanitized

- **WHEN** an execution event contains oversized, sensitive, or binary data
- **THEN** the persisted and returned representation applies the existing
  trace limits and redaction rules
- **AND** it never exposes credentials, raw image bytes, data URLs, or local
  source paths

### Requirement: Live execution and historical execution use one ordered model

The system SHALL expose the same versioned event shape for live delivery and
historical retrieval. A client SHALL be able to combine an initial historical
replay with subsequent live events by sequence number without duplicating or
reordering events.

#### Scenario: New client hydrates before following a live run

- **WHEN** a client opens a run after events have already been emitted
- **THEN** it receives the available prior events in sequence order and then
  receives later events as they are emitted
- **AND** each event is rendered at most once

#### Scenario: Disconnected client resumes from a sequence

- **WHEN** the event connection is interrupted after sequence N and the run is
  still available
- **THEN** the client can request events after sequence N and receive every
  later available event in order
- **AND** the client keeps already-rendered events without replacing them

#### Scenario: Event history is no longer available

- **WHEN** a run or its bounded event history has expired or been removed
- **THEN** the client receives an explicit unavailable or history-gap state
- **AND** it does not silently show an incomplete execution as complete

### Requirement: Execution trace groups related tool evidence

The system SHALL preserve one canonical run identifier across Gateway run
acceptance, Agent execution, durable memory records, execution events,
conversation projection, attachments, visual observations, and generated chart
artifacts. Every measurement, generation, review, and publication event that
participates in the decision timeline SHALL contain a complete `unit_id`,
`unit_type`, `phase`, `actor`, `role`, and `transition_id`. A tool call and its
result SHALL use the same `unit_id` and `call_id`; a review cycle SHALL use one
canonical `review_id` for its candidate attempt. The producer SHALL reject a
timeline event that is missing required identity or state fields instead of
creating a legacy or unknown association.

The grouping SHALL retain intermediate evidence when the final answer is
available, while allowing generated chart artifacts to be displayed as final
Run results instead of duplicated as ordinary tool-step content.

Each tool-result event SHALL keep its bounded `tool_name`, `call_id`, execution
status, unit correlation, and turn/run correlation in the outer event envelope
even when the structured result body is truncated. Truncation SHALL apply to
the diagnostic result payload rather than replacing the identity needed for
client correlation.

#### Scenario: One canonical identity is used across a Run

- **WHEN** the Gateway accepts a message and starts an Agent run
- **THEN** the Run summary, durable Agent records, emitted events, projected
  messages, and managed artifacts all identify that operation with the same
  canonical run identifier
- **AND** every timeline event has a complete semantic unit envelope

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client can render one step with running, success, or error state
  and expandable arguments and result details
- **AND** both events belong to the same canonical unit without tool-name or
  sequence guessing

#### Scenario: Missing timeline identity is rejected

- **WHEN** a producer attempts to persist a measurement, generation, review, or
  publication event without its required unit identity or state
- **THEN** the producer records a bounded protocol error and does not publish
  the malformed event to the user timeline
- **AND** the client does not synthesize a legacy, unknown, or orphan business
  step

#### Scenario: Oversized result preserves tool identity

- **WHEN** a tool result contains a trace, polyline, OCR collection, or other
  diagnostic payload larger than the event body limit
- **THEN** the event retains its bounded tool name, call identifier, unit
  identity, status, turn, and run correlation
- **AND** only the oversized result content is represented as truncated or
  summarized data

#### Scenario: Visual evidence remains attached to its tool context

- **WHEN** a tool produces a visual observation for a call
- **THEN** the observation can be displayed inside or alongside that tool step
  with its caption and authorized resource reference
- **AND** the event history keeps the observation order relative to the call
  and result under the same unit

#### Scenario: Generated chart remains available as Run output

- **WHEN** a Run produces a generated chart artifact
- **THEN** the artifact retains its canonical Run association, availability
  state, and authorized resource reference for the final result area
- **AND** the execution trace retains a bounded generation event without
  requiring the artifact preview to be duplicated inside the tool timeline

#### Scenario: Expired generated chart is explicit

- **WHEN** a generated chart artifact is unavailable or expired when the Run
  is restored
- **THEN** the final result area shows its bounded unavailable state and
  preserves the surrounding Run structure
- **AND** the trace does not claim that the artifact preview is available

#### Scenario: Identity mismatch is explicit and recoverable

- **WHEN** restored data contains a Run summary and conversation records that
  cannot be associated with one canonical run identifier
- **THEN** the client preserves the records and shows an explicit incomplete
  or unavailable association state
- **AND** it does not silently present the mismatched records as one complete
  successful Run

### Requirement: Final answers are safe Markdown documents

The system SHALL preserve the final answer source text and allow the desktop
client to render it as safe Markdown. Rendering SHALL support ordinary
headings, paragraphs, emphasis, lists, tables, links, and fenced code blocks
without exposing unsanitized HTML or replacing the original answer text.

#### Scenario: Structured final answer is readable

- **WHEN** an Agent returns a Markdown answer containing headings, a table, and
  a code block
- **THEN** the desktop client renders those structures in the final answer
  area with the original content semantics preserved

#### Scenario: Malicious Markdown is bounded

- **WHEN** the final answer contains raw HTML, unsafe links, or oversized
  content
- **THEN** the client applies the configured safe rendering policy and size
  limits
- **AND** unsafe markup does not execute in the desktop client

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL keep tool execution, measurement evidence, canonical
review, and publication status in independent fields. `tool_call`/`tool_result`
express measurement invocation and candidate result; new runs SHALL NOT emit
separate measurement decision, selection, discard, focus, or repair lifecycle
events. Measurement results SHALL NOT be interpreted as generated-chart review
outcomes. `review_started` and `review_completed` SHALL be public review
lifecycle events; Run lifecycle SHALL distinguish active, completed, failed,
interrupted, and history-gap.

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

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported user-facing lifecycle event, with the stable English event kind
preserved only as a machine identifier and technical detail. The user-facing
projection SHALL never use an unsupported event kind, `unknown`, or `legacy` as
visible fallback text. Unsupported or malformed event kinds SHALL remain
technical protocol errors and SHALL NOT create a business timeline item.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains
  the original event kind for technical inspection

#### Scenario: Malformed lifecycle event is not shown as a business step

- **WHEN** a client receives an event that is absent from the supported event
  contract or lacks its required semantic envelope
- **THEN** it displays a bounded protocol or history error state
- **AND** it does not display the raw English kind as a completed user-facing
  step

#### Scenario: Interruption reason is localized

- **WHEN** a client renders a supported interruption reason
- **THEN** it displays its bounded Simplified Chinese label and retains the
  machine reason code for diagnostics

### Requirement: Run history has one cursor and terminal contract

The execution trace SHALL use one monotonic per-run event sequence for live
and persisted events. A history replay SHALL preserve sequence order, identify
retention gaps explicitly, and include or resolve to the authoritative run
terminal state. A terminal run SHALL not gain later client-visible execution
events.

#### Scenario: Replay resumes after a known sequence

- **WHEN** a client requests a run history after sequence 12
- **THEN** the returned events have greater sequences in ascending order and
  belong to the same run

#### Scenario: History gap is represented explicitly

- **WHEN** sequence 12 is no longer retained but later events remain
- **THEN** the trace returns a bounded history-gap indication
- **AND** it does not silently present the remaining events as complete

#### Scenario: Terminal event remains authoritative

- **WHEN** a terminal event has been recorded and a late producer reports
  progress
- **THEN** the late progress is not appended to the client-visible trace
- **AND** the original terminal event and reason remain authoritative

### Requirement: Execution history deletion follows session lifecycle

The system SHALL remove durable execution history and managed visual artifacts
when their owning session is deleted, subject to the same authorization and
cleanup guarantees as session records and attachments.

#### Scenario: Deleting a session removes its trace

- **WHEN** the user confirms deletion of an idle session
- **THEN** its runs, execution events, final answers, and managed visual trace
  artifacts are no longer readable through the Gateway
- **AND** another session's execution history is unaffected

### Requirement: Generated chart preview references follow candidate publication

Generated chart lifecycle events SHALL expose enough bounded identity and
status information for a client to resolve both an unpublished candidate and
its later published artifact. When a candidate is promoted, subsequent
historical or live representations SHALL provide a current artifact reference
or a stable preview resolution that does not depend on a stale candidate URL.

#### Scenario: Pending candidate has a preview resource

- **WHEN** a generated chart candidate is persisted for review
- **THEN** its event contains the candidate identity and the client can request
  the candidate image for an authorized owning run while it remains available

#### Scenario: Published artifact replaces a candidate

- **WHEN** a review promotes a candidate to a published or warning publication
  state
- **THEN** the resulting event and later history expose the published artifact
  identity and preview resource, and the client does not continue relying only
  on the old candidate resource

#### Scenario: Historical lifecycle can resolve the current image

- **WHEN** the client reloads a run after candidate publication or receives a
  lifecycle event out of order
- **THEN** it can resolve the current preview using the available bounded
  reference and displays an explicit pending or unavailable state when no
  current bytes can be served

### Requirement: Run trace preserves effective provider metadata

Execution history SHALL carry the effective provider and model as bounded
metadata on run-start or model-turn events and in historical run summaries when
available. The metadata SHALL be immutable for a run and MUST exclude secrets,
raw endpoint values, and provider response bodies.

#### Scenario: Provider is attached to model boundaries

- **WHEN** an Agent run starts a model turn
- **THEN** the event identifies the snapshotted provider and model alongside
  the existing turn metadata

#### Scenario: Provider metadata is safe

- **WHEN** trace events are persisted or returned to the desktop client
- **THEN** provider metadata is bounded and contains no API key, endpoint, or
  raw provider payload

#### Scenario: Provider remains stable after switching

- **WHEN** the user changes the frontend selection after a run starts
- **THEN** historical and live events for that run continue to report its
  original provider

### Requirement: Execution checkpoints and continuation lineage are inspectable

The execution trace SHALL expose bounded checkpoint state and work-unit
completion information for runs that may be continued. A continuation SHALL
retain its parent run identifier and relation kind while using its own event
sequence. The trace SHALL keep the parent terminal state immutable and SHALL
make recovery-blocked or uncertain operations distinguishable from completed
work.

#### Scenario: Checkpoint is visible without exposing execution internals

- **WHEN** a run reaches a committed recovery boundary
- **THEN** its summary or trace exposes the checkpoint phase, next-action
  category, and recovery availability
- **AND** it does not expose secrets, raw provider responses, or binary content

#### Scenario: Resume lineage is preserved

- **WHEN** a resume creates a child run
- **THEN** the child trace identifies the parent and the `resume` relation
- **AND** the child events remain ordered independently from the parent's
  terminal event stream

#### Scenario: Uncertain operation is not shown as completed

- **WHEN** a run stops with an operation whose result cannot be confirmed
- **THEN** the trace records the bounded uncertain or recovery-blocked state
- **AND** it does not render that operation as a successful completed step

### Requirement: Candidate lifecycle events share stable scope correlation

候选生成、measurement tool observation、审核、修复和 publication 事件 SHALL 在适用时共享 `candidate_id`、attempt、source scope 和 repair kind。事件 SHALL 保持工具执行、measurement evidence、chart review 与 publication status 的语义分离；measurement evidence 的是否采用由实际 assembly 输入体现，不形成独立事件种类。

#### Scenario: Measurement and generated review are not displayed as one status

- **WHEN** 一个候选经历 measurement observation、assembly、`review_started` 和 generated-chart rejection
- **THEN** trace 保留各实际工具调用、审核和发布状态
- **AND** 关联字段允许客户端把它们归入同一 candidate attempt，但 measurement 成功不被解释为 review passed

### Requirement: Repair events identify the next permitted phase

每个审核失败或修复事件 SHALL 携带 bounded repair kind、父 attempt 和允许的下一阶段。
`evidence_needed` 事件 SHALL 能区分“等待主 Agent 决策”和“正在同范围补证据”；
`terminal` 事件 SHALL 表示不得继续。

#### Scenario: Evidence repair is traceable from failure to re-review

- **WHEN** review 失败后主 Agent 进行同范围补测并重新审核
- **THEN** trace 能通过父/子 attempt 连接失败、补测、重新装配和下一次审核
- **AND** 不会把多个 review lifecycle event 误显示为多次独立生成请求

### Requirement: Oversized diagnostic results preserve the scope identity

当 tool result 或 review diagnostic 被截断时，外层事件 SHALL 仍保留 tool name、call_id、
candidate_id、attempt、source scope 和 status；截断只影响诊断正文，不得造成孤立或未知
候选。

#### Scenario: Truncated measurement remains attributable

- **WHEN** 局部测量结果超过事件正文限制
- **THEN** 客户端仍能知道它属于哪个 candidate/panel attempt
- **AND** 可以通过授权引用获取完整结果或显示明确的 truncated 状态

### Requirement: Execution events expose decision-unit correlation

测量、装配、生成、审核、修复和发布相关的 execution event SHALL 在适用时携带统一的 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id`、`transition_id` 和 `next_action`。字段 SHALL 是有界、可序列化且与现有 run、candidate、attempt、scope 和 call 标识兼容的。

#### Scenario: Cross-domain events share a unit lineage

- **WHEN** 一个候选由 measurement tool observation、实际 assembly 输入和一次审核修复产生
- **THEN** 相关事件可以通过 unit 和 parent unit 关联到同一 candidate lineage
- **AND** 客户端可以区分 observation、action、gate 和 publication，而不需要独立 measurement-decision event

#### Scenario: Event without applicable parent remains valid

- **WHEN** 一个独立的工具观察没有父决策 unit
- **THEN** 事件可以使用自身的 observation unit 和空 parent
- **AND** 不得伪造一个不存在的 candidate 或 review 关系

### Requirement: Timeline events have one canonical payload shape

每个参与用户时间线的事件类型 SHALL 定义唯一的 envelope 字段形状和状态字段语义。新的 timeline correlation envelope SHALL 使用版本 2；envelope 标识字段 SHALL 使用当前运行事件协议约定的 `snake_case`。同一事件类型不得把 `state/status`、snake/camel 字段名或 Gate 别名作为可互换输入。不同公开 DTO（例如 Run summary）可以继续使用其既有字段约定，但不得把 DTO 别名注入事件 envelope。`tool_result` 的工具执行状态使用 `status`，其他生命周期状态使用该事件类型定义的 canonical 字段；生产端遇到同一语义的冲突或别名字段 SHALL 拒绝该时间线事件，不得选择一个值继续发布。

#### Scenario: Lifecycle event has one state field

- **WHEN** 生产端发出审核、生成或发布生命周期事件
- **THEN** 事件只包含该事件类型定义的 canonical 状态字段
- **AND** 客户端无需从另一个状态别名推断状态

#### Scenario: Tool result uses its declared execution status

- **WHEN** 生产端发出 `tool_result`
- **THEN** 外层事件使用该事件类型规定的工具执行状态字段，并保留 tool/call/unit/run 关联
- **AND** 不额外写入一个含义重复的生命周期状态别名

#### Scenario: Gate snapshots do not create parallel lifecycle events

- **WHEN** 权威审核状态变化并更新 Gateway 的 Gate 查询投影
- **THEN** 系统通过审核/发布业务事件表达相关领域转移
- **AND** 不另外发出 `review_gate_required` 或 `review_gate_updated` 镜像事件

#### Scenario: Conflicting aliases are rejected

- **WHEN** 一个时间线事件同时包含同一语义的多个字段，或仅提供该事件类型不支持的别名
- **THEN** 生产端记录有界协议错误并拒绝该事件进入可见事件历史
- **AND** 不通过优先级或“第一个非空值”静默选择状态

#### Scenario: Unsupported history protocol is explicit

- **WHEN** 客户端读取无法识别的时间线协议版本或字段形状
- **THEN** Gateway/客户端返回明确的不可用或不支持状态
- **AND** 不把该历史事件转换成成功、通过或已发布状态

### Requirement: Execution history supports deterministic decision projection

持久化 execution history SHALL 保留生成统一时间线所需的顺序、状态和关联字段。历史重放、实时追加和评测读取 SHALL 使用同一事件语义，不得因为不同入口而生成不同的 unit 分组。

#### Scenario: Live and replayed events project identically

- **WHEN** 客户端先读取历史事件，再接收同一 run 的实时事件
- **THEN** 两批事件合并后产生与完整历史读取相同的时间线
- **AND** 不产生重复 unit 或乱序状态

#### Scenario: Evaluation reads the same trace contract

- **WHEN** 评测工作台读取一个 case 的 run history
- **THEN** 事件中的 unit、phase、decision 和 gate 字段与普通运行读取时一致
- **AND** 评测层不需要访问原始 SQLite 或重新执行 Agent

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

### Requirement: Equivalent transitions are projected idempotently

同一 `run_id`、`unit_id`、`attempt`、`phase` 和 `transition_id` 的重复事件 SHALL 不创建重复的顶层时间线行。去重不得删除原始 event history，也不得隐藏相同 transition 的错误状态。

#### Scenario: Review snapshot does not duplicate review start

- **WHEN** review gate 和 tool result 都携带同一个 review start transition
- **THEN** timeline projection 只生成一个 review start 状态
- **AND** 原始事件仍然按 sequence 保留

### Requirement: Lifecycle events expose bounded process correlation

执行事件 SHALL 在可确定时携带有界的 process、turn、operation 或其他现有运行关联信息，并继续保留 run sequence 作为事实顺序。无法确定关联时，事件仍 SHALL 合法持久化并明确为未关联，不得伪造 candidate、unit 或 parent。

#### Scenario: Model and operation events share a process context

- **WHEN** 一个模型 turn 发起一个或多个工具 operation
- **THEN** 相关 lifecycle events 可以通过有界上下文归入同一过程展示
- **AND** 原始 sequence、call identity 和工具详情仍可单独展开

#### Scenario: Legacy events remain replayable

- **WHEN** 历史事件没有新增的过程关联字段
- **THEN** 系统按兼容规则持久化和投影这些事件
- **AND** 历史读取、实时追加和评测读取不会因为缺失字段而丢失事件或生成虚假 lineage

### Requirement: Execution failures carry deterministic classification

执行 trace SHALL 为失败事件保存有界的 failure category、stable code、provider status（如适用）、safe message、retryability 和第一失败引用。确定性拒绝与结果未知的失败 SHALL 使用不同的分类，不得都降级为 operation outcome uncertain。

#### Scenario: Deterministic provider error is persisted

- **WHEN** provider 明确返回不可接受当前请求的状态
- **THEN** trace 保存 provider failure 分类及其可展示原因
- **AND** trace 不生成表示远端是否已接受请求的 uncertain 结论

#### Scenario: Unknown remote outcome remains explicit

- **WHEN** 请求超时、连接中断或系统无法判断远端是否已接受操作
- **THEN** trace 标记 operation outcome uncertain 并保留恢复阻塞原因
- **AND** 用户可以看到这是结果未知，而不是已确认的 provider 拒绝
