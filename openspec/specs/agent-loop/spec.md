# agent-loop Specification

## Purpose

A minimal ReAct agent loop that drives a model through tool-calling turns until
it produces a final answer. It owns its conversation history in memory, executes
requested tool calls serially, feeds observations back to the model, and stops
on a final answer or an exhausted step budget.

## Requirements

### Requirement: Run a single user turn to completion

The system SHALL provide an `Agent` that, given a user input — either a plain
string or an OpenAI multimodal content list — drives a ReAct-style loop until
the model returns no tool calls and no required generated-chart review
obligation remains, or the step budget is exhausted, and SHALL return the
final text. The user input is appended to history and forwarded to the client
unchanged in either form.

#### Scenario: Returns after final answer

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns a
  turn with no tool calls while no review obligation is pending
- **THEN** the returned value is that final turn's text content

#### Scenario: Final answer is held while review is pending

- **WHEN** the model returns no tool calls while a required generated-chart
  candidate remains unpublished and unresolved
- **THEN** the Agent does not finalize that response and continues with bounded
  review-gate context identifying the required action

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

### Requirement: Agent uses a static behavior prompt and review obligations

The Agent SHALL use one stable system prompt for the lifetime of a run. The
prompt SHALL define evidence discipline, tool-selection principles, generated
chart review rules, and final-answer boundaries without encoding a mutable
analysis, generation, or review phase. When a generated chart creates a
pending review obligation, the model-visible context SHALL identify the
candidate references and required next action as bounded structured data.

#### Scenario: Ordinary turn uses the stable behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is
  pending
- **THEN** the model receives the configured system prompt and the normal
  registered tool surface
- **AND** the prompt explains that tool success, review completion, and
  publication are distinct outcomes

#### Scenario: Pending review is added as structured context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible observation includes the candidate ID, review
  ID, candidate status, review status, publication status, and required review
  action
- **AND** the Agent does not replace the stable system prompt with a
  phase-specific prompt

### Requirement: Agent keeps a stable review-tool surface while enforcing the gate

The Agent runtime SHALL expose the existing generated-chart review tool through
the normal run tool surface and SHALL preserve access to evidence, ChartSpec
correction, and bounded regeneration tools. An invalid or unavailable review
reference SHALL produce a bounded structured error, and the final-answer gate
SHALL remain code-enforced.

#### Scenario: Review tool is available without a phase switch

- **WHEN** a model turn is prepared before or after a chart candidate is
  created
- **THEN** the review transition schema is available through the normal tool
  surface without replacing the other registered tools

#### Scenario: Failed review can be repaired

- **WHEN** review evidence identifies a blocking mismatch
- **THEN** the model can collect additional evidence, revise the ChartSpec, and
  request a new bounded candidate while the previous candidate remains
  attributable and not silently promoted

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
