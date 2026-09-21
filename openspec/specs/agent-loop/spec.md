# agent-loop Specification

## Purpose

A minimal ReAct agent loop that drives a model through tool-calling turns until
it produces a final answer. It owns its conversation history in memory, executes
requested tool calls serially, feeds observations back to the model, and stops
on a final answer or an exhausted step budget.

## Requirements

### Requirement: Agent performs semantic chart review automatically without an exposed review tool

The Agent runtime SHALL invoke the internal tool-free VLM review path whenever
a generated candidate carries a semantic review obligation. The review
invocation SHALL be isolated from the main model's normal tool surface and
SHALL return bounded structured state to the Agent loop. The main model MAY
correct a failed candidate, but SHALL not submit or override the review
decision through a tool call or final text.

#### Scenario: Normal tool surface excludes the review transition

- **WHEN** the Agent prepares a model request before or after a generated chart
  candidate is created
- **THEN** the model receives the normal registered tools without
  `review_generated_chart`
- **AND** no review candidate or review decision tool schema is advertised

#### Scenario: Render completion triggers an isolated reviewer call

- **WHEN** a semantic-review-required candidate is produced by a rendering tool
- **THEN** the Agent invokes one additional VLM call with no tools
- **AND** the call is not appended as a user-visible main-agent tool exchange
- **AND** its bounded result is attached to the candidate's review lifecycle

#### Scenario: Failed review returns correction context

- **WHEN** the isolated VLM reviewer rejects a candidate and retry budget remains
- **THEN** the next main-agent context identifies the candidate, review state,
  bounded issues, and required corrective action
- **AND** the main Agent can call `assemble_spec` and `render_chart` for a new
  candidate while the rejected candidate remains unpublished

### Requirement: Agent distinguishes candidate previews from published artifacts

The Agent SHALL treat every `render_chart` result as an unpublished candidate
or preview until the code-owned publication gate promotes it. The static main
prompt SHALL identify `publicationStatus` as the authority for publication,
shall not treat `reviewStatus=completed` alone as a pass, and shall require the
Agent to use only bounded review diagnostics to correct a failed candidate.
The Agent SHALL not invoke OCR, CV, geometry, or layout tools after rendering
to replace or override the automatic VLM review.

#### Scenario: Rendered image remains a preview

- **WHEN** `render_chart` returns an image whose publication status is pending
  or unpublished
- **THEN** the Agent treats the image as a candidate preview
- **AND** it does not describe the image as verified or published
- **AND** it waits for or responds to the automatic review lifecycle

#### Scenario: Review completion does not imply publication

- **WHEN** a candidate has `reviewStatus=completed` but its normalized decision
  is `fail` or its `publicationStatus` is rejected
- **THEN** the Agent treats the candidate as failed
- **AND** it does not claim that the review passed or that the artifact was
  published

#### Scenario: Failed candidate follows the correction chain

- **WHEN** a failed candidate has retry budget remaining
- **THEN** the Agent uses only `decision`, `checks`, and bounded issue
  `code`, `location`, `severity`, and `message` as correction evidence
- **AND** it revises the ChartSpec, calls `assemble_spec`, and then calls
  `render_chart` for a new candidate
- **AND** it does not call a post-render evidence tool to substitute for VLM
  review

### Requirement: Run a single user turn to completion

The system SHALL provide an `Agent` that, given a user input — either a plain
string or an OpenAI multimodal content list — drives a ReAct-style loop until
the model returns no tool calls and no required generated-chart review
obligation remains, or the step budget is exhausted, and SHALL return the
final text. The user input is appended to history and forwarded to the client
unchanged in either form.
The run SHALL also accept a cooperative interruption signal, stop at a safe
loop boundary when the signal is observed, and SHALL not publish a final
answer for an interrupted run.

#### Scenario: Returns after final answer

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns a
  turn with no tool calls while no review obligation is pending
- **THEN** the returned value is that final turn's text content

#### Scenario: Final answer is held while review is pending

- **WHEN** the model returns no tool calls while a required generated-chart
  candidate remains unpublished and unresolved
- **THEN** the Agent does not finalize that response and continues with bounded
  review-gate context identifying the required action

#### Scenario: Failed review cannot be bypassed

- **WHEN** a required candidate has failed, timed out, or exhausted its review
  retries and the model returns no tool calls
- **THEN** the Agent does not mark the candidate published
- **AND** it returns a bounded non-published result or requires a bounded
  correction path rather than accepting the model's free-form final claim

#### Scenario: Stops at the step budget

- **WHEN** the model keeps requesting tool calls past the configured maximum
  steps, or a required review remains unresolved past the configured maximum
  steps
- **THEN** the loop stops and returns a bounded result indicating the budget or
  review gate was reached, without looping forever or publishing the candidate

#### Scenario: Multimodal user input passes through

- **WHEN** `Agent.run` is called with a multimodal content list (text part plus
  image part)
- **THEN** the user entry in history carries that content list unchanged, and
  the client receives it verbatim on the first model turn

#### Scenario: Interruption stops before the next work unit

- **WHEN** the interruption signal is observed before a model turn, tool call,
  rendering operation, or review action begins
- **THEN** the Agent exits the loop with a bounded interrupted outcome
- **AND** it does not begin that work unit or claim a completed final answer

#### Scenario: Late work result is ignored

- **WHEN** a provider or tool returns after the Agent has observed interruption
- **THEN** the result is not used to continue the loop or publish a final
  answer
- **AND** the caller can still finalize the run as interrupted

### Requirement: Agent cooperatively stops an interrupted run

The Agent SHALL check the interruption signal before each model request and
before each requested native tool dispatch, and SHALL check it again before
publishing tool observations, generated visuals, review context, or final
answer data. The checks SHALL be bounded and SHALL not change native message
ordering for work that completed before interruption was observed.

#### Scenario: Tool loop observes interruption between calls

- **WHEN** one tool call completes and the run is interrupted before the next
  model turn
- **THEN** the Agent records the completed tool result as bounded trace data
- **AND** it does not issue the next model request

#### Scenario: Generated observation races with interruption

- **WHEN** a generated visual result becomes available after interruption
- **THEN** the Agent does not expose it as new run progress or a final answer
- **AND** the run remains interruptible and terminalizable

### Requirement: Agent uses a layered behavior prompt and automatic review obligations

The Agent SHALL assemble a stable static responsibility layer together with a
runtime-derived tool surface, attributable process artifacts, and dynamic
Run/Turn state. The static layer SHALL define evidence discipline,
model-led semantic interpretation, adaptive tool-selection principles, atomic
ChartSpec assembly and validation, generated chart review rules, and
final-answer boundaries without encoding mutable analysis, generation, or
review state. The dynamic layers SHALL identify the current source, panel,
available tools, produced observations or candidates, publication state, and
bounded next action. The Agent SHALL allow the model to use multimodal visual
understanding as a first-pass hypothesis, select OCR, geometry, or layout tools
for unresolved source evidence, and use `assemble_spec` as the
model-facing construction-and-validation gate when a structured ChartSpec is
needed; it SHALL NOT require a separate `validate_spec` tool call, prescribe
`inspect_chart_layout` as a universal precondition, or ask the model to call a
chart-review tool. When a generated chart creates an automatic review
obligation, the model-visible dynamic context SHALL identify candidate
references, review result, publication state, and bounded required next action
as structured data. The prompt SHALL describe normalized review fields
(`decision`, `confidence`, `checks`, and `issues`) as system-provided evidence
to consume, not as a JSON decision that the main Agent may generate or
override.

#### Scenario: Ordinary turn uses the layered behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is
  pending
- **THEN** the model receives the static responsibility layer, the current registered tool surface, and the current Run/Turn context
- **AND** the context explains that visual understanding is a hypothesis, auxiliary tool observations are attributable evidence, `assemble_spec` performs the construction-and-validation gate, and tool success, review completion, and publication are distinct outcomes

#### Scenario: Model chooses targeted evidence

- **WHEN** a chart restoration turn contains uncertainty about text, geometry,
  orientation, or series association
- **THEN** the model can choose the corresponding OCR, chart sensor, or layout
  tool without following a fixed phase order
- **AND** the Agent keeps the resulting observations available as attributable process artifacts for the next model turn

#### Scenario: Clear chart does not require layout preflight

- **WHEN** the model has sufficient multimodal evidence to construct a valid
  ChartSpec for a clear chart
- **THEN** it can request `assemble_spec` without first requesting
  `inspect_chart_layout`
- **AND** the Agent does not inject an implicit layout requirement that blocks
  the assembly

#### Scenario: Structured output uses the atomic assembly gate

- **WHEN** the model has gathered enough evidence to return structured chart
  data or invoke `render_chart`
- **THEN** it requests `assemble_spec` before that downstream action
- **AND** a successful assembly is the only model-facing construction and
  validation step required for the ChartSpec
- **AND** an assembly error causes the model to revise, re-observe, or reassemble
  instead of returning or rendering the invalid candidate

#### Scenario: Runtime context exposes existing panel reuse

- **WHEN** a named session already contains a valid panel handoff for the current source
- **THEN** the next model turn receives the panel inventory and can use the stable `panel_id`
- **AND** the Agent does not require the model to rediscover the panel from incomplete prior history

#### Scenario: Pending review is added as structured context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible context includes the candidate ID, review ID, candidate status, review status, publication status, and required review action
- **AND** the Agent does not replace the static responsibility layer with a phase-specific system prompt

#### Scenario: Publication state controls the final claim

- **WHEN** the model prepares a final response after a generated chart
  candidate has been reviewed
- **THEN** it may call the chart published only when `publicationStatus` is
  `published` or `published_with_warning`
- **AND** it preserves the warning for `published_with_warning`
- **AND** it describes pending, rejected, failed, timed-out, or
  retry-exhausted candidates as not published

#### Scenario: Source evidence scope is explicit

- **WHEN** a source-linked candidate lacks authorized source evidence
- **THEN** the Agent does not claim that source-fidelity review completed
- **AND** a direct-data candidate without a source-fidelity obligation is not
  described as equivalent to a source image

### Requirement: Serial native tool-calling loop with observations

The system SHALL expose the agent's registered tools to the model and execute
each model-requested tool call through the tool registry. For every requested
call, it SHALL append a structured JSON `tool` message tied to the call ID. If
one or more calls also produce valid generated images, the system SHALL append
all required `tool` messages before adding a model-visible multimodal
observation containing the associated images and captions, then continue the
loop. The infrastructure SHALL NOT require the model to use, accept, retry, or
validate a visual observation.

#### Scenario: Execute requested JSON-only tool call

- **WHEN** the model requests a registered tool that returns only structured data
- **THEN** the tool is dispatched and its JSON result is appended as a `tool`
  message tied to the call ID with no additional multimodal observation

#### Scenario: Execute requested tool call with visual evidence

- **WHEN** the model requests a registered tool that returns structured data
  and a valid generated image
- **THEN** the call's JSON `tool` message is appended before a multimodal
  observation containing the image, caption, tool name, and call ID

#### Scenario: Multiple native calls preserve message ordering

- **WHEN** one assistant turn requests multiple tool calls and any of them
  produce generated images
- **THEN** one `tool` message is appended for every requested call before a
  combined multimodal observation is appended, preserving native protocol order

#### Scenario: Structural tool error is fed back

- **WHEN** a requested tool fails (unknown name or raised error) and `dispatch`
  returns a structured `{"error": ...}`
- **THEN** that structured error is appended as the observation instead of
  raising, and the loop continues so the model can recover

#### Scenario: Model may ignore visual evidence

- **WHEN** a visual observation is available but the model can answer without
  another tool call
- **THEN** the model may return its final answer without a mandatory validation
  action or fixed acceptance threshold

### Requirement: Agent owns its message history in memory

 The system SHALL manage Agent history through a session-memory boundary. The
 default implementation SHALL retain running history only in memory, while an
 explicitly selected named session MAY durably restore completed prior runs.
 In both modes, the Agent SHALL send only valid bounded context produced by that
 boundary and SHALL allow reset or a new session to start without prior context.

#### Scenario: History accumulates across steps

- **WHEN** an agent run performs multiple tool-calling steps
- **THEN** assistant turns (with their tool calls) and tool observations are all
  retained in the agent's history so the model sees its prior actions

#### Scenario: Reset starts a new history

- **WHEN** the agent is reset or built anew
- **THEN** its history restarts and later runs no longer share prior messages

#### Scenario: Named memory supplies bounded prior context

- **WHEN** an Agent is connected to a resumed named session
- **THEN** it receives valid bounded context from completed runs without taking
  direct responsibility for database storage or binary attachment persistence

### Requirement: Keeps assistant tool calls in history

The system SHALL construct assistant history entries that include the model's
`tool_calls` when present, unlike the conversation loop which strips them, so a
multi-step agent can still reference its own prior actions. The system SHALL
preserve native tool-message ordering: when one assistant turn contains
multiple tool calls, every corresponding `tool` result SHALL be appended in the
original call order before any new user or assistant continuation message,
including measurement repair context.

#### Scenario: Assistant turn retains tool calls

- **WHEN** a model turn carries tool calls
- **THEN** the appended assistant entry includes those tool calls, not only the
  text content

#### Scenario: Multiple tool calls retain a valid contiguous result sequence

- **WHEN** one assistant turn carries multiple tool calls and one or more tool
  results produce follow-up guidance
- **THEN** the history contains the assistant tool-call entry followed by one
  matching `tool` entry for every call in the original order
- **AND** repair or other continuation guidance is appended only after the
  complete tool-result sequence

#### Scenario: Reasoning stays out of history

- **WHEN** a model turn carries provider reasoning
- **THEN** that reasoning is not echoed into the assistant history entry (to keep
  deep-thinking providers valid)

### Requirement: Step budget guard

The system SHALL accept a configurable maximum step count and SHALL enforce it
to prevent unbounded loops.

#### Scenario: Configurable budget

- **WHEN** an agent is constructed with a `max_steps`
- **THEN** the loop performs at most `max_steps` tool-calling turns before
  stopping

### Requirement: Agent execution trace hook

The Agent SHALL allow an optional trace consumer to observe execution events
without changing the native tool-message ordering, multimodal observation
ordering, returned final answer, or step-budget behavior.

#### Scenario: Trace observes a model turn and tool call

- **WHEN** the model returns a tool call during an Agent run with tracing enabled
- **THEN** the trace consumer receives a model-turn event followed by a
  tool-call event containing the tool name, call identifier, and arguments

#### Scenario: Trace observes tool completion before the next model turn

- **WHEN** a requested tool completes successfully or with a structured error
- **THEN** the trace consumer receives a tool-result event before the Agent
  invokes the model again, including success/error status and bounded data

#### Scenario: Trace observes termination

- **WHEN** an Agent run returns a final answer or reaches its step budget
- **THEN** the trace consumer receives a corresponding final-answer or
  budget-exhausted event

### Requirement: Agent resumes from a committed execution checkpoint

The Agent SHALL be able to start a continuation from a validated checkpoint
that contains bounded conversation context, completed tool results, visual
evidence references, layout context, and review/publication references. It SHALL
continue from the checkpoint's next action, reuse completed operations, and
preserve the existing interruption and terminal rules. It SHALL return a
bounded recovery-blocked outcome rather than automatically replaying an
uncertain provider, tool, rendering, review, or publication operation.

#### Scenario: Continuation starts after a completed tool result

- **WHEN** an explicit resume provides a checkpoint after a committed tool
  result
- **THEN** the Agent reconstructs the safe model context and begins at the
  checkpoint's next action
- **AND** the prior tool call is not dispatched again

#### Scenario: Layout and chart evidence survive continuation

- **WHEN** a checkpoint contains authorized layout, visual, candidate, or
  publication references
- **THEN** the resumed Agent can use those references in later chart reasoning
- **AND** it does not require the original process-local state to be present

#### Scenario: Uncertain operation stops automatic continuation

- **WHEN** the checkpoint identifies a provider or tool operation whose result
  is uncertain and no replay-safe contract exists
- **THEN** the Agent does not dispatch that operation automatically
- **AND** the caller receives a bounded recovery-blocked result that can be
  followed by an explicit retry

### Requirement: Recoverable review failures return to the main Agent

当生成候选的审核失败且仍有重试预算时，Agent loop SHALL 收到结构化审核诊断并继续运行。对于语义或渲染问题，主 Agent SHALL 能够提交修正后的 ChartSpec 并生成新候选；对于源绑定问题，流程 SHALL 优先修复源上下文。

#### Scenario: Semantic failure triggers a corrected candidate

- **WHEN** VLM review 拒绝候选并返回具体语义问题
- **THEN** 主 Agent 收到该问题而不是立即得到最终失败答复
- **AND** 主 Agent 可以 assemble 新 ChartSpec、render 新候选并进入下一次审核

### Requirement: Exhausted review recovery terminates explicitly

当源绑定或候选修复达到上限时，Agent loop SHALL 以明确的非发布状态结束，保留失败原因和候选 lineage，不得绕过审核门禁发布最后一个失败候选。

#### Scenario: Retry budget is exhausted

- **WHEN** 所有允许的审核修复或重试次数均已使用
- **THEN** run 状态为 retry_exhausted 或等价的非发布失败状态
- **AND** 用户可以看到下一步是重新绑定源图还是调整规格

### Requirement: Agent keeps measurement evidence decisions bounded

Agent loop SHALL 将测量返回的 observation scope、evidence refs、issues、focus suggestion、attempt lineage 和主 Agent 的选择结果作为有界的模型上下文保存。多个 measurement session 的上下文 SHALL 保持来源、面板和 attempt 边界；主 Agent 的显式局部补充、重复目标拒绝、舍弃和预算耗尽 SHALL 以结构化状态反馈，但不得隐式创建全量重测或独占主链路。

#### Scenario: Observation returns decision context to the model

- **WHEN** 测量工具返回候选、warning 或局部结果
- **THEN** Agent 将结构化问题、evidence refs、overlay、scope 和下一动作交给模型
- **AND** 系统不要求模型先通过独立 measurement review 才能继续观察

#### Scenario: Multiple measurements retain independent evidence contexts

- **WHEN** 同一个 assistant 工具批次中的多个测量结果分别绑定不同的 panel 或 measurement session
- **THEN** Agent 保留每个 measurement session 的 attachment、panel、attempt、父 attempt、证据引用和选择状态
- **AND** 任何一个 session 的结果都不会因为另一个结果后到达而被覆盖

#### Scenario: Measurement target exhaustion remains bounded

- **WHEN** 主 Agent 重复提交相同 target、来源身份失配或超过局部补充次数上限
- **THEN** Agent 停止该补充分支并保留可恢复的 checkpoint、失败原因和 lineage
- **AND** 其他合法观察或直接视觉路径不被错误标记为生成审核失败

### Requirement: Measurement repair remains compatible with direct assembly

当模型没有引用测量证据而直接基于清晰视觉输入组装合法 ChartSpec 时，Agent SHALL 保持直接装配路径。即使当前 run 曾经产生未采用、partial 或失败的 observation，模型也可以明确放弃该 observation 后直接装配；该路径不得绕过 ChartSpec 结构校验和后续生成审核。

#### Scenario: Direct visual assembly does not enter measurement repair mode

- **WHEN** 模型提交没有 measurement provenance 的合法单图或图表集合装配请求
- **THEN** Agent 按现有 ChartSpec 校验和生成审核流程继续
- **AND** 不创建虚假的 measurement session 或 repair attempt

#### Scenario: Unused observation remains auditable

- **WHEN** 模型放弃一个已有 measurement attempt 并改用视觉或 OCR 证据
- **THEN** Agent 保留该 attempt 的历史和 abandoned 决策
- **AND** 不阻塞当前合法的组装请求

### Requirement: Main-chain measurement decisions are model-led

主 Agent SHALL 在同一主链路中消费测量工具返回的结构化结果、稳定证据引用、overlay、观察范围和质量警告，并自主决定选择候选、舍弃误检、映射语义、请求局部补充或停止。系统不得通过独立测量审核器替主 Agent 作出语义选择。

#### Scenario: Main Agent accepts a usable observation

- **WHEN** 测量工具返回候选结果且主 Agent 判断现有证据足以支持目标图表
- **THEN** 主 Agent 可以提交 selected/discarded refs 和语义映射到 `assemble_spec`
- **AND** 系统不自动发起额外测量

#### Scenario: Main Agent requests an initial scoped observation

- **WHEN** 主 Agent 在第一次测量前能够判断 plot 或 legend 的大致范围
- **THEN** 主 Agent 可以提交 `observation_scope`
- **AND** 该调用不要求先存在父 attempt

#### Scenario: Main Agent requests focused evidence

- **WHEN** 主 Agent 发现某个候选、系列、基准线或局部区域仍不确定
- **THEN** 主 Agent 可以再次调用对应的原测量工具并提供 `measurement_target`
- **AND** 该工具调用被记录为新的有父级关系的 measurement attempt

#### Scenario: Main Agent discards a false candidate

- **WHEN** 主 Agent 根据证据引用和源图像判断某个候选是图例、文字或其他误检
- **THEN** 主 Agent 可以在装配请求中排除该引用
- **AND** 系统不得因为该候选存在 warning 而自动重测整个 panel

### Requirement: Measurement warnings do not schedule hidden tool calls

测量工具、质量审计、checkpoint 恢复和 review gate 更新 SHALL 不得仅根据 warning、`repair_action` 或 `remeasure_required` 状态自动创建或执行下一次测量调用。所有局部重测 SHALL 出现在主 Agent 的显式 tool call 中；其他观察工具不得因为测量 warning 被隐式跳过。

#### Scenario: Warning returns control to the main model

- **WHEN** 一次测量返回基准线冲突、系列未解析或覆盖不完整 warning
- **THEN** 下一轮主 Agent 上下文包含 bounded warning、候选引用、scope 和可选 focus suggestion
- **AND** 在主 Agent 选择前没有新的 measurement tool call

#### Scenario: Recovery resumes without repeating a completed measurement

- **WHEN** Agent 从 checkpoint 或断线状态恢复，且最近一次测量已经完成
- **THEN** 恢复状态停留在等待主 Agent 决策的阶段
- **AND** 恢复流程不得重新执行相同的测量调用

### Requirement: Assembly is blocked until the main-chain evidence decision is explicit

主循环 SHALL 要求使用 measurement evidence 的 `assemble_spec` 请求携带主 Agent 的 selected/discarded decision，并校验来源、范围、引用和幂等约束；该要求不得扩展为“整个 attempt 必须 accepted”。未被选择的候选可以被舍弃，未采用的 observation 可以被放弃，只有被选中的非法证据或结构化 ChartSpec 才能阻止当前组装。

#### Scenario: Assembly receives an explicit candidate decision

- **WHEN** 主 Agent 根据 overlay 和 evidence refs 提交 selected/discarded refs
- **THEN** 系统校验 decision 属于当前 attachment、panel 和 attempt
- **AND** 如果 selected refs 合法，组装可以继续，即使同一 attempt 仍有非阻断 warning

#### Scenario: Invalid candidate decision is rejected safely

- **WHEN** 主 Agent 提交不存在、越界、来源失配或互相重叠的 refs
- **THEN** 系统返回结构化 decision error
- **AND** 不自动重测、不发布、不把模型的最终文本当作通过依据
