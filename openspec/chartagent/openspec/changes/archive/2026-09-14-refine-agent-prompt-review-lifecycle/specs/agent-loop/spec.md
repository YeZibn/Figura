## MODIFIED Requirements

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

- **WHEN** the model keeps requesting tool calls, or a required review remains
  unresolved, past the configured maximum steps
- **THEN** the loop stops and returns a bounded result indicating the budget or
  review gate was reached, without looping forever or publishing the candidate

#### Scenario: Multimodal user input passes through

- **WHEN** `Agent.run` is called with a multimodal content list (text part plus
  image part)
- **THEN** the user entry in history carries that content list unchanged, and
  the client receives it verbatim on the first model turn

## ADDED Requirements

### Requirement: Agent uses a static behavior prompt and review obligations

The Agent SHALL use one stable system prompt for the lifetime of a run. The
prompt SHALL define evidence discipline, tool-selection principles, generated
chart review rules, and final-answer boundaries without encoding a mutable
analysis, generation, or review phase. When a generated chart creates a
pending review obligation, the model-visible context SHALL identify the
candidate references and required next action as bounded structured data.

#### Scenario: Ordinary turn uses the stable behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is pending
- **THEN** the model receives the configured system prompt and the normal registered tool surface
- **AND** the prompt explains that tool success, review completion, and publication are distinct outcomes

#### Scenario: Pending review is added as structured context

- **WHEN** a generated chart creates an unresolved review obligation
- **THEN** the next model-visible observation includes the candidate ID, review ID, candidate status, review status, publication status, and required review action
- **AND** the Agent does not replace the stable system prompt with a phase-specific prompt

### Requirement: Agent keeps a stable review-tool surface while enforcing the gate

The Agent runtime SHALL expose the existing generated-chart review tool through
the normal run tool surface and SHALL preserve access to evidence, ChartSpec
correction, and bounded regeneration tools. An invalid or unavailable review
reference SHALL produce a bounded structured error, and the final-answer gate
SHALL remain code-enforced.

#### Scenario: Review tool is available without a phase switch

- **WHEN** a model turn is prepared before or after a chart candidate is created
- **THEN** the review transition schema is available through the normal tool
  surface without replacing the other registered tools

#### Scenario: Failed review can be repaired

- **WHEN** review evidence identifies a blocking mismatch
- **THEN** the model can collect additional evidence, revise the ChartSpec, and
  request a new bounded candidate while the previous candidate remains
  attributable and not silently promoted

