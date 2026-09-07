# agent-loop Specification

## Purpose

A minimal ReAct agent loop that drives a model through tool-calling turns until
it produces a final answer. It owns its conversation history in memory, executes
requested tool calls serially, feeds observations back to the model, and stops
on a final answer or an exhausted step budget.

## ADDED Requirements

### Requirement: Run a single user turn to completion

The system SHALL provide an `Agent` that, given a user input, drives a
ReAct-style loop until the model returns no tool calls (final answer) or the
step budget is exhausted, and SHALL return the final text.

#### Scenario: Returns after final answer

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns a
  turn with no tool calls
- **THEN** the returned value is that final turn's text content

#### Scenario: Stops at the step budget

- **WHEN** the model keeps requesting tool calls past the configured maximum
  steps
- **THEN** the loop stops and returns a bounded result indicating the budget was
  reached, without looping forever

### Requirement: Serial native tool-calling loop with observations

The system SHALL expose the agent's registered tools to the model, and for each
model-requested tool call SHALL execute it via the tool registry and append the
structured result back into the history as an observation.

#### Scenario: Execute requested tool call

- **WHEN** the model requests a registered tool call
- **THEN** the tool is dispatched and its JSON result is appended to the history
  as a `tool` message tied to the call id, so the next model turn can see it

#### Scenario: Structural tool error is fed back

- **WHEN** a requested tool fails (unknown name or raised error) and `dispatch`
  returns a structured `{"error": ...}`
- **THEN** that structured error is appended as the observation instead of
  raising, and the loop continues so the model can recover

### Requirement: Agent owns its message history in memory

The system SHALL keep the running message history inside the agent instance for
the duration of a run, and SHALL allow a fresh run or reset to start a new
history.

#### Scenario: History accumulates across steps

- **WHEN** an agent run performs multiple tool-calling steps
- **THEN** assistant turns (with their tool calls) and tool observations are all
  retained in the agent's history so the model sees its prior actions

#### Scenario: Reset starts a new history

- **WHEN** the agent is reset or built anew
- **THEN** its history restarts and later runs no longer share prior messages

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