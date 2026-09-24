## MODIFIED Requirements

### Requirement: Agent can request chart generation through the tool boundary

The Agent SHALL be able to request rendering of a ChartSpec through a
registered tool. The tool SHALL return structured chart metadata together with
an attributed visual payload when rendering succeeds. A rendered candidate
whose policy requires semantic review SHALL be submitted automatically to the
internal tool-free VLM review path; the Agent SHALL not choose review tools or
submit a free-form review decision. When a generated chart requires review,
the Agent SHALL treat the rendered image as a preview and SHALL not publish it
or present it as an unqualified final result until the required review gate has
completed and the code-owned `publicationStatus` permits that claim.

#### Scenario: User asks to redraw data recovered from an attached chart

- **WHEN** a user asks the Agent to redraw data recovered from an attached
  chart
- **THEN** the Agent can reuse or assemble a ChartSpec, validate it, request a
  chart candidate, and inspect the candidate through the normal visual
  observation path
- **AND** the system automatically sends the source-linked candidate to the
  internal tool-free VLM reviewer
- **AND** the Agent must wait for the required review result before claiming
  that the generated chart is verified

#### Scenario: Review does not call auxiliary chart tools

- **WHEN** a generated chart candidate enters semantic review
- **THEN** the review path does not invoke OCR, chart sensors, layout inspection,
  geometry measurement, or `review_generated_chart`
- **AND** the VLM receives the source image when available, the candidate image,
  and the immutable ChartSpec as its review context

#### Scenario: Agent inspects generated visual evidence

- **WHEN** a chart-rendering tool returns a valid visual payload
- **THEN** the Agent can receive the generated chart as attributed visual
  evidence on a later model turn and may use the automatic review result to
  accept, retry, or explain the candidate
- **AND** the structured chart and review metadata remain available
  independently

#### Scenario: Rendering failure is recoverable

- **WHEN** rendering fails because the input is invalid or a configured output
  limit is exceeded
- **THEN** the tool returns a bounded structured error or warning
- **AND** the Agent run remains able to revise the request or provide a text
  answer without an uncaught renderer exception

#### Scenario: Review failure is recoverable

- **WHEN** the internal VLM review identifies a semantic or fidelity mismatch
- **THEN** the candidate is not published as a valid generated chart
- **AND** bounded review diagnostics are provided so the Agent can revise the
  ChartSpec and request a bounded retry or provide a transparent failure
  explanation without an uncaught exception

#### Scenario: Final answer cannot bypass pending or failed review

- **WHEN** the Agent attempts to finish a run while a generated chart review is
  pending, failed, timed out, or retry-exhausted
- **THEN** the run remains bounded by the review gate or returns an explicit
  non-published result
- **AND** the generated chart is not marked as published

#### Scenario: Completed review is not itself a publication decision

- **WHEN** a review call reaches `reviewStatus=completed`
- **THEN** the Agent and Gateway use the normalized decision and
  `publicationStatus` to determine whether the candidate is publishable
- **AND** a completed review with `decision: fail` or a rejected publication
  status remains unpublished

### Requirement: Generated chart review is a mandatory publication gate

After a generated chart is created, the system SHALL use a post-generation
transition to place the chart in `review_pending` before final publication.
The gate SHALL require the applicable deterministic structural and encoded
artifact safety checks for every generated chart and SHALL require an
automatic internal VLM semantic review when the chart is derived from an
attached source image or otherwise carries an explicit review requirement.
The review VLM SHALL receive the source image when available, the candidate
image, and the immutable ChartSpec without any review or evidence tools. Neither
the Agent nor a caller SHALL bypass a pending or failed gate.

#### Scenario: Post-generation hook enters automatic review state

- **WHEN** a rendering operation produces a generated chart candidate
- **THEN** the post-generation transition records `review_pending` before the
  candidate can become a final generated-chart artifact
- **AND** a semantic-review-required candidate automatically triggers one
  tool-free VLM review call
- **AND** the review state is bound to the run, candidate reference, and
  ChartSpec version

#### Scenario: Safety checks and semantic review are distinct

- **WHEN** any generated chart candidate is created
- **THEN** structural ChartSpec validation, render and layout safety checks, and
  encoded-artifact checks applicable to that candidate complete before
  publication
- **AND** a source-linked or explicitly review-required candidate also receives
  the automatic VLM semantic review
- **AND** neither a safety-check pass nor a VLM pass can be omitted from the
  applicable publication gate

#### Scenario: Source-linked generation requires VLM semantic comparison

- **WHEN** a candidate is generated from an attached source image or from data
  whose semantic provenance requires review
- **THEN** the system requires a VLM comparison of the source image, ChartSpec,
  and candidate image before publication
- **AND** the comparison covers chart type, orientation, categories, series
  identity, values, labels, baseline or geometry relationships, and material
  unresolved ambiguity
- **AND** the comparison path invokes no OCR, CV, geometry, layout, or review
  tool

#### Scenario: Direct data generation uses the applicable review scope

- **WHEN** a candidate is generated only from user-supplied structured data
  with no source-image fidelity claim
- **THEN** the candidate passes all applicable deterministic generation and
  artifact safety checks before publication
- **AND** the result does not claim source-image equivalence when no source
  image was supplied

#### Scenario: VLM review pass promotes the candidate

- **WHEN** all applicable safety checks complete and the internal VLM returns a
  valid non-blocking decision
- **THEN** the candidate transitions to a verified or warning publication state
  according to the decision and review policy
- **AND** only then can the Gateway expose it as a final generated-chart
  artifact

#### Scenario: Recoverable warning remains explicit

- **WHEN** VLM review completes with a bounded non-blocking readability or
  semantic uncertainty warning that policy permits publishing
- **THEN** the chart may be published with review status `warning`
- **AND** the warning is visible in structured metadata and the final run
  projection without being represented as an unqualified pass

#### Scenario: Blocking VLM review failure prevents publication

- **WHEN** VLM review finds missing data, wrong orientation, wrong category
  order, series misidentification, value mismatch, label misassociation,
  baseline misalignment, unreadable critical content, or another configured
  blocking issue
- **THEN** the candidate transitions to `review_failed` and no final artifact
  reference is issued
- **AND** the Agent may submit a corrected ChartSpec for a bounded new
  candidate

#### Scenario: Review state is idempotent and candidate-specific

- **WHEN** the same post-generation event is delivered more than once or an
  internal VLM result is retried
- **THEN** the system does not publish duplicate artifacts or apply a review
  result to a different candidate or ChartSpec version
- **AND** the final state remains attributable to the original run and review
  record

#### Scenario: Timeout and retry limits are bounded

- **WHEN** the internal VLM review call or candidate retry times out or fails
  repeatedly
- **THEN** the system records a bounded review timeout or retry-exhausted state
- **AND** it does not leave an indefinitely pending candidate or publish it as
  verified
