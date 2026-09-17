## ADDED Requirements

### Requirement: Agent performs semantic chart review automatically without an exposed review tool

The Agent runtime SHALL invoke the internal tool-free VLM review path whenever a
generated candidate carries a semantic review obligation. The review invocation
SHALL be isolated from the main model's normal tool surface and SHALL return
bounded structured state to the Agent loop. The main model MAY correct a failed
candidate, but SHALL not submit or override the review decision through a tool
call or final text.

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
obligation remains, or a pending, failed, timed-out, or retry-exhausted review
reaches the configured termination boundary, or the step budget is exhausted,
and SHALL return the final text or a bounded non-published result. The user
input is appended to history and forwarded to the client unchanged in either
form.

#### Scenario: Returns after final answer and successful review

- **WHEN** `Agent.run(user_input)` is called and the model eventually returns a
  turn with no tool calls while no review obligation is pending or failed
- **THEN** the returned value is that final turn's text content

#### Scenario: Final answer is held while review is pending

- **WHEN** the model returns no tool calls while a required generated-chart
  candidate remains unpublished and unresolved
- **THEN** the Agent does not finalize that response and continues with bounded
  review-gate context identifying the candidate and required corrective action

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

### Requirement: Agent uses a static behavior prompt and automatic review obligations

The Agent SHALL use one stable system prompt for the lifetime of a run. The
prompt SHALL define evidence discipline, model-led semantic interpretation,
adaptive tool-selection principles, atomic ChartSpec assembly and validation,
automatic generated-chart review rules, and final-answer boundaries without
encoding a mutable analysis, generation, or review phase. The prompt SHALL
allow the model to use multimodal visual understanding as a first-pass
hypothesis, select OCR, geometry, or layout tools for unresolved source
evidence, and use `assemble_spec` as the model-facing construction-and-
validation gate when a structured ChartSpec is needed; it SHALL NOT require a
separate `validate_spec` tool call, prescribe `inspect_chart_layout` as a
universal precondition, or ask the model to call a chart-review tool. When a
generated chart creates an automatic review obligation, the model-visible
context SHALL identify the candidate references, review result, publication
state, and bounded required next action as structured data. The prompt SHALL
describe the normalized review fields (`decision`, `confidence`, `checks`, and
`issues`) as system-provided evidence to consume, not as a JSON decision that
the main Agent may generate or override.

#### Scenario: Ordinary turn uses the stable behavior contract

- **WHEN** the Agent requests a model turn before any generated chart review is
  pending
- **THEN** the model receives the configured system prompt and the normal
  registered tool surface
- **AND** the prompt explains that visual understanding is a hypothesis,
  auxiliary tool observations are attributable evidence, `assemble_spec`
  performs the construction-and-validation gate, automatic VLM review and
  publication are code-enforced, and tool success, review completion, and
  publication are distinct outcomes

#### Scenario: Model chooses targeted source evidence

- **WHEN** a chart restoration turn contains uncertainty about text, geometry,
  orientation, or series association before generation
- **THEN** the model can choose the corresponding OCR, chart sensor, or layout
  tool without following a fixed phase order
- **AND** the Agent keeps the resulting observations available for the next
  model turn

#### Scenario: Clear chart can assemble directly

- **WHEN** the model has sufficient multimodal evidence to construct a valid
  ChartSpec for a clear chart
- **THEN** it can request `assemble_spec` without first requesting
  `inspect_chart_layout`
- **AND** the Agent does not inject an implicit layout requirement that blocks
  the assembly

#### Scenario: Assembly remains the construction gate

- **WHEN** the model has gathered enough evidence to return structured chart
  data or invoke `render_chart`
- **THEN** it requests `assemble_spec` before that downstream action
- **AND** a successful assembly is the only model-facing construction and
  validation step required for the ChartSpec
- **AND** an assembly error causes the model to revise, re-observe, or reassemble
  instead of returning or rendering the invalid candidate

#### Scenario: Automatic review state is added as structured context

- **WHEN** a generated chart creates an unresolved, failed, or warning review
  outcome
- **THEN** the next model-visible observation includes the candidate ID, review
  ID, candidate status, review status, publication status, bounded review
  diagnostics, and required next action
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

## REMOVED Requirements

### Requirement: Agent keeps a stable review-tool surface while enforcing the gate

The Agent runtime SHALL expose the existing generated-chart review tool through
the normal run tool surface and SHALL preserve access to evidence, ChartSpec
correction, and bounded regeneration tools. An invalid or unavailable review
reference SHALL produce a bounded structured error, and the final-answer gate
SHALL remain code-enforced.

#### Scenario: Model turn exposes the review transition schema

- **WHEN** a model turn is prepared before or after a chart candidate is
  created
- **THEN** the review transition schema is available through the normal tool
  surface without replacing the other registered tools

#### Scenario: Review evidence can trigger correction

- **WHEN** review evidence identifies a blocking mismatch
- **THEN** the model can collect additional evidence, revise the ChartSpec, and
  request a new bounded candidate while the previous candidate remains
  attributable and not silently promoted

**Reason**: Semantic review is now an automatic internal VLM call. Exposing a
review transition tool creates an optional path that the main model may omit or
misuse, and it contradicts the requirement that review not invoke tools.

**Migration**: Remove `review_generated_chart` from the Agent registry and
prompt contract. Use the automatically produced structured review state to
correct the ChartSpec and render a new candidate; keep `assemble_spec` and
`render_chart` as the model-facing correction and generation tools.
