## MODIFIED Requirements

### Requirement: Run a single user turn to completion

The system SHALL provide an `Agent` that, given a user input — either a plain
string or an OpenAI multimodal content list — drives a ReAct-style loop until
the model returns no tool calls and no required generated-chart review
obligation remains, or the step budget is exhausted, and SHALL return the
final text. The user input is appended to history and forwarded to the client
unchanged in either form. The run SHALL also accept a cooperative interruption
signal, stop at a safe loop boundary when the signal is observed, and SHALL
not publish a final answer for an interrupted run.

#### Scenario: Returns after final answer

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns
  a turn with no tool calls while no review obligation is pending
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
- **THEN** the loop stops and returns a bounded result indicating the budget
  or review gate was reached, without looping forever or publishing the
  candidate

#### Scenario: Multimodal user input passes through

- **WHEN** `Agent.run` is called with a multimodal content list (text part
  plus image part)
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

## ADDED Requirements

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

