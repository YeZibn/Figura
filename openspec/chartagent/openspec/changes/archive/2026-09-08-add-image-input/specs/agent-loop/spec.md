## MODIFIED Requirements

### Requirement: Run a single user turn to completion

The system SHALL provide an `Agent` that, given a user input — either a plain
string or an OpenAI multimodal content list — drives a ReAct-style loop until
the model returns no tool calls (final answer) or the step budget is exhausted,
and SHALL return the final text. The user input is appended to history and
forwarded to the client unchanged in either form.

#### Scenario: Returns after final answer

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns a
  turn with no tool calls
- **THEN** the returned value is that final turn's text content

#### Scenario: Stops at the step budget

- **WHEN** the model keeps requesting tool calls past the configured maximum
  steps
- **THEN** the loop stops and returns a bounded result indicating the budget was
  reached, without looping forever

#### Scenario: Multimodal user input passes through

- **WHEN** `Agent.run` is called with a multimodal content list (text part plus
  image part)
- **THEN** the user entry in history carries that content list unchanged, and
  the client receives it verbatim on the first model turn
