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
conversation projection, attachments, visual observations, and generated
chart artifacts. It SHALL preserve enough call, observation, and artifact
identifiers for clients to associate a tool call with its result, error,
visual evidence, and generated chart output. The grouping SHALL retain
intermediate evidence when the final answer is available, while allowing
generated chart artifacts to be displayed as final Run results instead of
duplicated as ordinary tool-step content.

Each tool-result event SHALL keep its bounded `tool_name`, `call_id`, execution
status, and turn/run correlation in the outer event envelope even when the
structured result body is truncated. Truncation SHALL apply to the diagnostic
result payload rather than replacing the identity needed for client
correlation.

#### Scenario: One canonical identity is used across a Run

- **WHEN** the Gateway accepts a message and starts an Agent run
- **THEN** the Run summary, durable Agent records, emitted events, projected
  messages, and managed artifacts all identify that operation with the same
  canonical run identifier
- **AND** no second local Run identifier causes the conversation projection
  and execution history to describe separate runs

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client can render one step with running, success, or error state
  and expandable arguments and result details
- **AND** the step remains associated with its parent canonical Run

#### Scenario: Oversized result preserves tool identity

- **WHEN** a tool result contains a trace, polyline, OCR collection, or other
  diagnostic payload larger than the event body limit
- **THEN** the event retains its bounded tool name, call identifier, status,
  turn, and run correlation
- **AND** only the oversized result content is represented as truncated or
  summarized data
- **AND** clients do not create an unknown or orphan tool step solely because
  the result body was truncated

#### Scenario: Visual evidence remains attached to its tool context

- **WHEN** a tool produces a visual observation for a call
- **THEN** the observation can be displayed inside or alongside that tool step
  with its caption and authorized resource reference
- **AND** the event history keeps the observation order relative to the call
  and result under the same Run

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

Lifecycle events SHALL 保持工具执行、measurement observation、evidence decision、生成图审核和 publication status 的独立字段。`measurement_observed`、`measurement_evidence_selected`、`measurement_evidence_discarded` 和 `measurement_repair_exhausted` 等事件不得被解释为生成图审核通过或失败；`chart_review_started` 仅表示生成候选进入审核。Run lifecycle events SHALL 继续区分 active、completed、failed 和 interrupted。

#### Scenario: Tool result reports observation state only

- **WHEN** 一个 OCR 或图表测量工具完成
- **THEN** `tool_result` 和对应 observation 事件独立报告执行状态、scope、refs、质量 warning 和 overlay
- **AND** 工具成功不会自动产生 accepted、published 或 generated review passed 状态

#### Scenario: Evidence decision records model agency

- **WHEN** 主 Agent 选择、舍弃或放弃一次 observation
- **THEN** trace 记录对应 attempt、selected/discarded refs、语义映射和 decision 来源
- **AND** 原始工具结果仍保持可追溯

#### Scenario: Generated review has accurate semantics

- **WHEN** 生成候选进入审核、修复或发布
- **THEN** trace 使用独立的 chart review 和 publication 状态
- **AND** 客户端不会把测量 observation 或 assemble 成功显示为已发布

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported lifecycle event, with the stable English event kind preserved as
the machine identifier. Unknown event kinds SHALL remain renderable using a
safe English fallback. Supported run terminal and interruption reason codes
SHALL also have bounded Simplified Chinese presentation labels.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains
  the original event kind for technical inspection

#### Scenario: Unknown lifecycle event remains visible

- **WHEN** a client receives an event kind absent from the label catalog
- **THEN** it displays the stable event kind as fallback text
- **AND** it does not discard or misclassify the event

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

### Requirement: Measurement repair lifecycle is inspectable

执行追踪 SHALL 区分普通 measurement observation、首次 scope、定向重测、证据选择、repair action 被拒绝和修复预算耗尽。相关事件 SHALL 保留 bounded run、panel、attempt、父 attempt、scope/target 类型、selected/discarded 状态和下一动作摘要，但不得记录原始图片、绝对路径、密钥或 provider 原始 payload。

#### Scenario: A scoped observation is correlated with its panel

- **WHEN** Agent 根据模型提供的 observation scope 发起测量
- **THEN** trace 可以关联 scope、panel、attempt、实际应用区域和结果状态
- **AND** 客户端能够区分首次范围观察与后续局部重测

#### Scenario: A repair attempt is correlated with its parent

- **WHEN** Agent 根据某次 observation 的问题发起定向重测
- **THEN** trace 可以关联 repair request、子 attempt、父 attempt、panel 和结果状态
- **AND** 客户端能够区分修复测量与新的无关观察

#### Scenario: Exhausted repair is explicit

- **WHEN** 定向重测无法收敛或达到预算上限
- **THEN** trace 发布明确的 repair-exhausted 或等价非发布状态及下一动作
- **AND** 该状态不被错误归类为 generated chart review failure

### Requirement: Measurement repair events have stable client presentation

执行追踪面向客户端的事件契约 SHALL 支持 measurement observation、`measurement_evidence_selected`、`measurement_repair_required`、`measurement_repair_rejected` 和 `measurement_repair_exhausted` 等事件。客户端 SHALL 保留稳定的英文事件类型，并为 observation、选择、舍弃、需要重测、修复被拒绝和预算耗尽提供有界的简体中文展示标签和诊断摘要。

#### Scenario: Selection event preserves correlation fields

- **WHEN** 客户端接收 measurement evidence selection 事件
- **THEN** 事件仍可通过 run、panel、attempt、selected refs 和 discarded refs 关联到对应运行
- **AND** 原始图片、绝对路径、密钥和 provider 原始 payload 不进入用户可见事件正文

#### Scenario: Replay and live delivery share the same presentation

- **WHEN** 同一 observation 或 decision 事件先通过历史回放返回、再通过实时流或重连流到达
- **THEN** 客户端使用相同的事件类型、标签和字段解释
- **AND** 按 run 与 sequence 去重，不产生第二条重复的用户可见事件
### Requirement: Candidate lifecycle events share stable scope correlation

候选生成、测量 observation、证据决策、审核、修复和 publication 事件 SHALL 共享
`candidate_id`、`attempt`、`source_scope` 和适用的 `repair_kind`。事件仍 SHALL 保持
工具执行、measurement evidence、chart review 和 publication status 的语义分离。

#### Scenario: Measurement and review are not displayed as one status

- **WHEN** 一个候选经历 measurement_observed、evidence_selected、chart_review_started
  和 generated_chart_rejected
- **THEN** trace 保留每种事件的独立 kind 和状态
- **AND** 关联字段允许客户端把它们归入同一 candidate attempt
- **AND** 任一 measurement 成功不会被解释成 review passed

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

- **WHEN** 一个候选由一次测量决策和一次审核修复产生
- **THEN** 相关事件可以通过 unit 和 parent unit 关联到同一 candidate lineage
- **AND** 客户端可以区分 observation、decision、action、gate 和 publication

#### Scenario: Event without applicable parent remains valid

- **WHEN** 一个独立的工具观察没有父决策 unit
- **THEN** 事件可以使用自身的 observation unit 和空 parent
- **AND** 不得伪造一个不存在的 candidate 或 review 关系

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

带有必需下一动作的事件 SHALL 保留 `required`、允许动作、阻塞动作和 bounded reason。事件序列 SHALL 能区分“动作已请求”“动作已应用”“动作已观察”“动作已决策”和“动作已终止”。

#### Scenario: Applied scope does not imply observed evidence

- **WHEN** trace 收到 measurement focus applied 但没有对应 observation
- **THEN** trace 保留 pending next action
- **AND** run terminal summary 不得把该 focus 当作已完成测量

#### Scenario: Explicit abandonment is terminally visible

- **WHEN** Agent 选择放弃一次可选测量或证据候选
- **THEN** trace 记录 abandonment reason 和被放弃的 unit
- **AND** 后续候选不会引用一个未被选择的 evidence ref

### Requirement: Equivalent transitions are projected idempotently

同一 `run_id`、`unit_id`、`attempt`、`phase` 和 `transition_id` 的重复事件 SHALL 不创建重复的顶层时间线行。去重不得删除原始 event history，也不得隐藏相同 transition 的错误状态。

#### Scenario: Review snapshot does not duplicate review start

- **WHEN** review gate 和 tool result 都携带同一个 review start transition
- **THEN** timeline projection 只生成一个 review start 状态
- **AND** 原始事件仍然按 sequence 保留
