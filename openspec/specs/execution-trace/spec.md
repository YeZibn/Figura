# execution-trace Specification

## Purpose

为 Agent Run 提供有界、可排序的公开事件历史，并与私有执行记录及模型上下文区分；支持实时观察、历史读取和安全终态呈现。
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
artifacts. Every measurement, generation, verification, and promotion event that
participates in the decision timeline SHALL contain a complete `unit_id`,
`unit_type`, `phase`, `actor`, `role`, and `transition_id`. A tool call and its
result SHALL use the same `unit_id` and `call_id`; each generated image SHALL
use its committed staged reference and verification reference as stable
identity. The producer SHALL reject a timeline event that is missing required
identity or state fields instead of creating an unknown association.

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

- **WHEN** a producer attempts to persist a measurement, generation,
  verification, or artifact event without its required unit identity or state
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
- **AND** 不伪造 pending measurement unit 或将其归类为图像验证失败

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

### Requirement: Oversized diagnostic results preserve the scope identity

当 tool result、来源绑定诊断或图像验证诊断被截断时，外层事件 SHALL 仍保留 bounded
tool name、call_id、unit identity、来源范围引用和 status；截断只影响诊断正文，不得造成
孤立工具结果或虚构业务状态。

#### Scenario: Truncated measurement remains attributable

- **WHEN** 局部测量结果超过事件正文限制
- **THEN** 客户端仍能知道它属于哪个工具调用、来源范围和验证结果
- **AND** 可以通过授权引用获取完整结果或显示明确的 truncated 状态

### Requirement: Execution events expose committed-fact correlation

测量、装配、生成、验证和发布相关的 execution event SHALL 在适用时携带统一的 `unit_id`、`unit_type`、`phase`、`actor`、`parent_unit_id` 和 `transition_id`。字段 SHALL 有界、可序列化，并与 run、staged reference、verification reference、scope 和 call 标识兼容；恢复控制游标不得成为业务时间线事件。

#### Scenario: Cross-domain events share a unit lineage

- **WHEN** 一张图由 measurement tool observation、实际 assembly 输入、渲染、验证和发布产生
- **THEN** 相关事件可以通过 unit 与 parent unit 关联到同一张图
- **AND** 客户端可以区分工具观察、生成、验证、正式 artifact 和终态，而不需要额外 decision 或 gate 事件

#### Scenario: Event without applicable parent remains valid

- **WHEN** 一个独立的工具观察没有父决策 unit
- **THEN** 事件可以使用自身的 observation unit 和空 parent
- **AND** 不得伪造一个不存在的生成、验证或父子关系

### Requirement: Timeline events have one canonical payload shape

每个参与用户时间线的事件类型 SHALL 定义唯一的 envelope 字段形状和状态字段语义。新的 timeline correlation envelope SHALL 使用版本 2；envelope 标识字段 SHALL 使用当前运行事件协议约定的 `snake_case`。同一事件类型不得把 `state/status`、snake/camel 字段名或 Gate 别名作为可互换输入。不同公开 DTO（例如 Run summary）可以继续使用其既有字段约定，但不得把 DTO 别名注入事件 envelope。`tool_result` 的工具执行状态使用 `status`，其他生命周期状态使用该事件类型定义的 canonical 字段；生产端遇到同一语义的冲突或别名字段 SHALL 拒绝该时间线事件，不得选择一个值继续发布。

#### Scenario: Verification and artifact events have one state field

- **WHEN** 生产端发出验证、生成或 artifact 生命周期事件
- **THEN** 事件只包含该事件类型定义的 canonical 状态字段
- **AND** 客户端无需从另一个状态别名推断状态

#### Scenario: Tool result uses its declared execution status

- **WHEN** 生产端发出 `tool_result`
- **THEN** 外层事件使用该事件类型规定的工具执行状态字段，并保留 tool/call/unit/run 关联
- **AND** 不额外写入一个含义重复的生命周期状态别名

#### Scenario: Committed facts do not create mirror events

- **WHEN** Gateway 保存已提交的图像验证结果或 artifact 结果
- **THEN** 系统通过对应的验证或发布事实事件表达转移
- **AND** 不从查询投影再生成重复的镜像事件

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
- **THEN** 事件中的 unit、phase、state 和来源关联与普通运行读取时一致
- **AND** 评测层不需要访问原始 SQLite 或重新执行 Agent

### Requirement: Equivalent transitions are projected idempotently

同一 `run_id`、`unit_id`、`attempt`、`phase` 和 `transition_id` 的重复事件 SHALL 不创建重复的顶层时间线行。去重不得删除原始 event history，也不得隐藏相同 transition 的错误状态。

#### Scenario: Repeated verification transition does not create a duplicate

- **WHEN** SSE 与历史补偿都携带同一个 chart verification transition
- **THEN** timeline projection 只生成一个验证结果
- **AND** 原始事件仍然按 sequence 保留

### Requirement: Lifecycle events expose bounded process correlation

执行事件 SHALL 在可确定时携带有界的 process、turn、operation 或其他现有运行关联信息，并继续保留 run sequence 作为事实顺序。无法确定关联时，事件仍 SHALL 合法持久化并明确为未关联，不得伪造 unit 或 parent 关联。

#### Scenario: Model and operation events share a process context

- **WHEN** 一个模型 turn 发起一个或多个工具 operation
- **THEN** 相关 lifecycle events 可以通过有界上下文归入同一过程展示
- **AND** 原始 sequence、call identity 和工具详情仍可单独展开

#### Scenario: Unsupported legacy protocol is explicit

- **WHEN** 历史事件没有新增的过程关联字段
- **THEN** Gateway 或客户端按不支持的历史协议返回有界不可用状态
- **AND** 不从旧 lifecycle 字段迁移或合成缺失的关联信息

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

### Requirement: Execution events represent committed tool, verification and artifact facts

公开执行事件 SHALL 使用同一 Run 内单调序号及稳定 transition/correlation identity，分别表达工具过程、验证结论、正式 artifact 和终态；未提交的内部结果不得投影为完成。测量质量仍作为工具事实，不建立采用/舍弃事件。验证和发布分别使用各自已提交的结论与 artifact 引用，不叠加并行状态字段或固定处理阶段。

#### Scenario: Verification and promotion appear once
- **WHEN** 一张图验证通过并正式发布，随后事件被重放
- **THEN** 时间线仍只有一个可归属的验证结果和一个正式产物结果
- **AND** 不从未提交的内部状态或旧候选状态字段推断额外转换

#### Scenario: Failed staged image has bounded context
- **WHEN** 验证失败且暂存预览可用
- **THEN** 事件含有生成尝试、来源范围、issues 与预览引用
- **AND** 不暴露图像字节、私有模型上下文或本地路径

### Requirement: Recovery trace exposes a cursor without controlling execution

Run 历史 SHALL 可见有界 resume 资格、不可用原因、父子 Run 关系及下一动作类别；内部执行记录负责恢复控制。SSE 重放 SHALL 继续以 runId:sequence 去重，并且历史缺口 SHALL 明确呈现。

#### Scenario: Child resume remains attributable
- **WHEN** 子 Run 从父 Run 的已提交游标继续
- **THEN** 两个 Run 各自保留事件序号和终态
- **AND** 历史可识别它们的 resume 关系
