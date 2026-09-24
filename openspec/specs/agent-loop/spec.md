# agent-loop Specification

## Purpose

A minimal ReAct agent loop that drives a model through tool-calling turns until
it produces a final answer. It owns its conversation history in memory, executes
requested tool calls serially, feeds observations back to the model, and stops
on a final answer or an exhausted step budget.

## Requirements

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
including bounded continuation context.

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

### Requirement: Agent keeps measurement evidence decisions bounded

Agent loop SHALL 将 measurement observation 的 scope、evidence refs、issues、overlay、attempt lineage 和实际被下游引用的 refs 作为有界上下文保存。多个 measurement session SHALL 保持来源、面板和 attempt 边界；系统 SHALL NOT 要求主 Agent先创建独立 selected/discarded/abandoned decision unit 才能调用 `assemble_spec`。

#### Scenario: Observation returns evidence facts to the model

- **WHEN** 测量工具返回候选、warning 或局部结果
- **THEN** Agent 将结构化问题、refs、overlay、scope 和非强制建议交给模型
- **AND** 上下文不包含替模型规定普通业务动作的 allowed/blocked action contract

#### Scenario: Multiple measurements retain independent evidence contexts

- **WHEN** 同一个 assistant 工具批次中的多个测量结果分别绑定不同 panel 或 session
- **THEN** Agent 保留每个 session 的 attachment、panel、attempt、父 attempt 和证据引用
- **AND** 任一 session 都不会因另一个结果后到达而被覆盖

#### Scenario: Used evidence is derived from the assembly request

- **WHEN** 主 Agent 在 `assemble_spec` 中引用当前 attempt 的部分 refs
- **THEN** 系统将这些 refs 记录为本次装配实际使用的 provenance
- **AND** 未引用候选无需逐项生成 discarded decision

### Requirement: Measurement repair remains compatible with direct assembly

当模型没有引用测量 evidence refs 而直接基于清晰视觉输入组装合法 ChartSpec 时，Agent SHALL 保持直接装配路径。任何未被引用、partial 或失败的 measurement observation 都不要求显式放弃，也不得阻塞合法装配；该路径仍必须经过 ChartSpec 结构校验和后续生成审核。

#### Scenario: Direct visual assembly does not enter measurement repair mode

- **WHEN** 模型提交没有 measurement provenance 的合法单图或图表集合装配请求
- **THEN** Agent 按现有 ChartSpec 校验和生成审核流程继续
- **AND** 不创建虚假的 measurement session 或 repair attempt

#### Scenario: Unused observation needs no abandonment decision

- **WHEN** 模型改用视觉或 OCR 证据而没有在 assembly 中引用某次 measurement attempt
- **THEN** Agent 保留该工具调用和原始结果作为运行历史
- **AND** 不创建 abandoned decision、额外测量状态或组装门禁

### Requirement: Main-chain measurement decisions are model-led

主 Agent SHALL 在同一主链路中消费测量工具结果并自主决定使用哪些候选、忽略哪些误检、映射语义、请求局部补充或改用直接视觉理解。系统 SHALL 通过工具输入和实际 evidence refs 记录可追踪事实，不得要求模型维护额外的 measurement decision 状态机，也不得通过独立测量审核器替模型作出语义选择。

#### Scenario: Main Agent uses a candidate subset

- **WHEN** 测量工具返回的部分候选足以支持目标图表
- **THEN** 主 Agent可以只把实际使用的 refs 传给 `assemble_spec`
- **AND** 系统验证这些 refs 后继续，不要求提交 discarded refs

#### Scenario: Main Agent requests an initial scoped observation

- **WHEN** 主 Agent 能够判断 plot 或 legend 的大致范围
- **THEN** 主 Agent 可以提交 `observation_scope`
- **AND** 该调用不要求父 attempt 或预先登记的 decision

#### Scenario: Main Agent requests focused evidence

- **WHEN** 主 Agent判断某个候选、系列、基准线或区域仍不确定
- **THEN** 主 Agent可以调用对应测量工具并提供 `measurement_target`
- **AND** 该调用创建有父级关系的新 attempt，但不锁定后续修复工具顺序

#### Scenario: Main Agent ignores a false candidate

- **WHEN** 主 Agent判断某个候选是图例、文字或其他误检
- **THEN** 主 Agent可以不在装配输入中引用该候选
- **AND** 系统不要求单独提交舍弃状态，也不自动重测整个 panel

### Requirement: Assembly validates actual evidence use without a separate decision envelope

主循环 SHALL 允许 `assemble_spec` 直接接收模型实际使用的 `measurement_ref + evidence_refs`，或接收不带 measurement provenance 的合法视觉输入。系统 SHALL 只校验实际引用的 refs 及其 session、attachment、panel、attempt、scope、引用存在性和必要结构；装配 schema 和运行状态不得接受、推导或要求 `measurement_decision`、selected/discarded refs 或 decision status。

#### Scenario: Referenced evidence is valid

- **WHEN** 主 Agent 提交属于当前来源和 attempt 的合法 evidence refs
- **THEN** 组装继续并从实际输入保存 provenance
- **AND** 同一 observation 中未引用的候选不会阻塞组装

#### Scenario: Referenced evidence is invalid

- **WHEN** 主 Agent 提交不存在、越界、跨来源或结构不完整的 ref
- **THEN** 系统返回定位到该 ref 的结构化错误
- **AND** 不自动重测、不渲染、不发布依赖该引用的结果

#### Scenario: Direct visual assembly remains available

- **WHEN** 主 Agent 不引用测量结果而提交合法 ChartSpec
- **THEN** 系统执行通常的结构校验和生成审核
- **AND** 当前 run 中未使用的 measurement observation 不要求 decision 或 abandonment 事件

### Requirement: Measurement warnings do not schedule hidden tool calls

测量工具、质量审计和 checkpoint 恢复 SHALL NOT 仅根据 warning、`repair_action` 或质量状态自动创建或执行下一次测量调用。局部重测必须作为主 Agent 的显式测量 tool call 出现在主链路中；恢复只需将当前 measurement session/attempt 事实提供给模型，不维护独立 repair queue，也不因缺少 decision 阻塞模型继续工作。

#### Scenario: Warning returns control to the main model

- **WHEN** 一次测量返回基准线冲突、系列未解析或覆盖不完整 warning
- **THEN** 下一轮主 Agent 上下文包含 bounded warning、候选引用、scope 和可选局部线索
- **AND** 主 Agent 决定是否直接装配、使用其他观察工具或显式调用局部测量

#### Scenario: Recovery resumes without repeating a completed measurement

- **WHEN** Agent 从 checkpoint 或断线状态恢复，且最近一次测量已经完成
- **THEN** 恢复上下文包含相同 session/current attempt 和工具结果
- **AND** 恢复流程不重放相同测量、不恢复 pending decision 或隐式创建新调用

### Requirement: Agent runs one turn through committed actions

Agent SHALL 按模型响应、有序工具调用、自动生成图验证与最终回答推进一个用户请求；文本和多模态输入的原始结构 SHALL 保持有效。模型无工具调用时，只有不存在未决必需验证且最终产物引用均已正式发布，Run 才能成功完成。中断信号 SHALL 在安全边界停止新工作，迟到结果不得覆盖中断终态。

#### Scenario: Final text with no generation
- **WHEN** 模型结束且没有工具调用或未决生成图
- **THEN** Agent 提交最终回答并完成 Run

#### Scenario: Pending generated image blocks success
- **WHEN** 模型试图用未验证的暂存图作最终成功回答
- **THEN** Agent 不完成成功 Run
- **AND** 继续有界验证或返回明确未完成原因

### Requirement: Agent resumes from the committed next action

显式续接 SHALL 使用受限私有执行记录和已提交 checkpoint 重建必要模型上下文，从下一动作继续。Agent SHALL 复用已提交工具与验证结果，并按副作用契约处理未提交动作；不可核对外部副作用不得自动重放。

#### Scenario: Completed tool is not repeated
- **WHEN** 子 Run 从工具结果后的 checkpoint 恢复
- **THEN** 模型看到该结果且工具不重新执行

### Requirement: Verification failures return bounded facts to the main Agent

生成图验证失败 SHALL 向主 Agent 返回暂存尝试、来源范围、issues、修复提示和剩余预算。Agent SHALL 自主选择合法观察、测量、装配、重新生成或停止；提示内容不得自动调度工具、形成自动 repair phase 或工具白名单，也不得限制可用工具。预算耗尽 SHALL 以明确非成功终态保留诊断。

#### Scenario: Evidence repair is model selected
- **WHEN** 验证返回 evidence-needed 诊断
- **THEN** Agent 可以显式选择当前授权范围的测量工具
- **AND** 新图仍经过完整验证

### Requirement: Layered prompt exposes verification facts

主 Agent 的分层提示 SHALL 描述工具、ChartSpec、证据范围及自动验证/发布事实。运行时层只提供当前已提交的暂存尝试、验证结果及正式 artifact 引用；未提交或非权威状态不得暗示成功。

#### Scenario: Failed output is explained without a gate snapshot
- **WHEN** 暂存图的验证失败
- **THEN** 下一模型上下文包含有界 issues 与来源绑定
- **AND** 不包含另一份可变 gate 状态
