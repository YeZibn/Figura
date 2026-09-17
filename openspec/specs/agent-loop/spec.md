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

### Requirement: Agent uses a static behavior prompt and automatic review obligations

The Agent SHALL use one stable system prompt for the lifetime of a run. The
prompt SHALL define evidence discipline, model-led semantic interpretation,
adaptive tool-selection principles, atomic ChartSpec assembly and validation,
generated chart review rules, and final-answer boundaries without encoding a
mutable analysis, generation, or review phase. The prompt SHALL allow the
model to use multimodal visual understanding as a first-pass hypothesis,
select OCR, geometry, or layout tools for unresolved source evidence, and use
`assemble_spec` as the model-facing construction-and-validation gate when a
structured ChartSpec is needed; it SHALL NOT require a separate
`validate_spec` tool call, prescribe `inspect_chart_layout` as a universal
precondition, or ask the model to call a chart-review tool. When a generated
chart creates an automatic review obligation, the model-visible context SHALL
identify the candidate references, review result, publication state, and
bounded required next action as structured data. The prompt SHALL describe
the normalized review fields (`decision`, `confidence`, `checks`, and
`issues`) as system-provided evidence to consume, not as a JSON decision that
the main Agent may generate or override.

#### Scenario: Ordinary turn uses the stable behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is
  pending
- **THEN** the model receives the configured system prompt and the normal
  registered tool surface
- **AND** the prompt explains that visual understanding is a hypothesis,
  auxiliary tool observations are attributable evidence, `assemble_spec`
  performs the construction-and-validation gate, and tool success, review
  completion, and publication are distinct outcomes

#### Scenario: Model chooses targeted evidence

- **WHEN** a chart restoration turn contains uncertainty about text, geometry,
  orientation, or series association
- **THEN** the model can choose the corresponding OCR, chart sensor, or layout
  tool without following a fixed phase order
- **AND** the Agent keeps the resulting observations available for the next
  model turn

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

#### Scenario: Pending review is added as structured context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible observation includes the candidate ID, review
  ID, candidate status, review status, publication status, and required review
  action
- **AND** the Agent does not replace the stable system prompt with a
  phase-specific prompt

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
multi-step agent can still reference its own prior actions.

#### Scenario: Assistant turn retains tool calls

- **WHEN** a model turn carries tool calls
- **THEN** the appended assistant entry includes those tool calls, not only the
  text content

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
