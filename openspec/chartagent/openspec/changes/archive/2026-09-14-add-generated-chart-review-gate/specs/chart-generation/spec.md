## MODIFIED Requirements

### Requirement: Agent can request chart generation through the tool boundary

The Agent SHALL be able to request rendering of a ChartSpec through a
registered tool. The tool SHALL return structured chart metadata together with
an attributed visual payload when rendering succeeds, and SHALL permit the
Agent to decide which evidence and correction actions to use without imposing
a fixed tool order. When a generated chart requires review, the Agent SHALL
not publish it or present it as an unqualified final result until the required
review gate has completed.

#### Scenario: User asks to redraw understood data

- **WHEN** a user asks the Agent to redraw data recovered from an attached
  chart
- **THEN** the Agent can reuse or assemble a ChartSpec, validate it, request a
  chart candidate, and inspect the candidate through the normal visual
  observation path
- **AND** the Agent must complete the required semantic review before claiming
  that the generated chart is a verified result

#### Scenario: Agent chooses its review evidence

- **WHEN** a generated chart candidate is pending review
- **THEN** the Agent may choose OCR, chart sensors, visual inspection, or a
  revised ChartSpec in any order supported by the available tools
- **AND** the system preserves the review gate even when the Agent changes
  tools or retries the candidate

#### Scenario: Review failure is recoverable

- **WHEN** the required review identifies a semantic or fidelity mismatch
- **THEN** the candidate is not published as a valid generated chart
- **AND** the Agent can revise the ChartSpec and request a bounded retry or
  provide a transparent failure explanation without an uncaught exception

#### Scenario: Final answer cannot bypass pending review

- **WHEN** the Agent attempts to finish a run while a generated chart review is
  still pending
- **THEN** the run remains in the review flow and the generated chart is not
  marked as published
- **AND** the Agent receives bounded structured state identifying the required
  review action

### Requirement: Generated chart output is bounded and attributable

Every generated chart candidate and published generated chart SHALL expose
bounded metadata that distinguishes its lifecycle state. A candidate SHALL
have an opaque candidate reference, chart type, bounded title, media type,
byte count, dimensions, and the identity of the ChartSpec version it represents.
A published chart SHALL additionally expose its opaque artifact reference,
review status, and bounded review diagnostics. Artifact metadata SHALL NOT
contain local source paths, credentials, raw provider payloads, or embedded
image bytes. Generated output SHALL remain distinguishable from temporary
model-observation images.

#### Scenario: Candidate output is attributable but not final

- **WHEN** rendering produces a chart that passes the applicable deterministic
  renderer and artifact checks but still requires semantic review
- **THEN** the result identifies the output as a review-pending candidate
- **AND** it includes bounded references that associate the candidate with the
  current run and ChartSpec version
- **AND** it does not expose the candidate as a verified final artifact

#### Scenario: Verified output metadata is safe

- **WHEN** a candidate passes all required checks
- **THEN** the published result contains bounded metadata and an opaque artifact
  reference suitable for Gateway and desktop-client retrieval
- **AND** the JSON result contains no raw image bytes or local filesystem path
- **AND** the metadata identifies whether the result was verified cleanly or
  published with an explicit warning

#### Scenario: Pending or failed candidates are not published

- **WHEN** a candidate has pending, failed, expired, or timed-out review state
- **THEN** it cannot be retrieved through the final generated-chart artifact
  route
- **AND** its bounded failure state remains attributable to the run without
  exposing image bytes or local paths

#### Scenario: Output limits and artifact validity remain enforced

- **WHEN** a candidate exceeds the configured byte or dimension limit, cannot
  be fully decoded as the declared image type, or fails an artifact integrity
  check
- **THEN** the system rejects it before publication with an explicit bounded
  reason
- **AND** it does not create a verified artifact or continue the review as if
  the candidate were valid

## ADDED Requirements

### Requirement: Generated chart review is a mandatory publication gate

After a generated chart is created, the system SHALL use a post-generation
transition to place the chart in `review_pending` before final publication.
The gate SHALL require the applicable deterministic checks for every generated
chart and SHALL require an independent semantic review when the chart is
derived from an attached source image or otherwise carries an explicit review
requirement. The Agent MAY control the choice and order of review evidence,
but neither the Agent nor a caller SHALL bypass a pending or failed gate.

#### Scenario: Post-generation hook enters review state

- **WHEN** a rendering operation produces a generated chart candidate
- **THEN** the post-generation transition records `review_pending` before the
  candidate can become a final generated-chart artifact
- **AND** the review state is bound to the run, candidate reference, and
  ChartSpec version

#### Scenario: Deterministic checks are mandatory for every candidate

- **WHEN** any generated chart candidate is created
- **THEN** structural ChartSpec validation, render-fidelity checks, layout or
  readability checks, and encoded-artifact checks applicable to that candidate
  must complete before publication
- **AND** a failed blocking check moves the candidate to a bounded failed state
  without publishing it

#### Scenario: Source-linked generation requires semantic review

- **WHEN** a candidate is generated from an attached source image or from data
  whose semantic provenance requires review
- **THEN** the system requires a semantic comparison of the source evidence,
  ChartSpec, and candidate image before publication
- **AND** the comparison covers chart type, categories, series identity,
  values, labels, and material unresolved ambiguity

#### Scenario: Direct data generation uses the applicable review scope

- **WHEN** a candidate is generated only from user-supplied structured data
  with no source-image fidelity claim
- **THEN** the candidate still passes all deterministic generation and artifact
  checks before publication
- **AND** the result does not claim source-image equivalence when no source
  image was supplied

#### Scenario: Review pass promotes the candidate

- **WHEN** all required checks complete with no blocking issue
- **THEN** the candidate transitions to a verified or warning publication state
  according to its bounded diagnostics
- **AND** only then can the Gateway expose it as a final generated-chart
  artifact

#### Scenario: Recoverable warning remains explicit

- **WHEN** review completes with a bounded non-blocking readability or semantic
  uncertainty warning that policy permits publishing
- **THEN** the chart may be published with review status `warning`
- **AND** the warning is visible in structured metadata and the final run
  projection without being represented as an unqualified pass

#### Scenario: Blocking review failure prevents publication

- **WHEN** independent review finds missing data, wrong category order, series
  misidentification, value mismatch, unreadable critical content, or another
  configured blocking issue
- **THEN** the candidate transitions to `review_failed` and no final artifact
  reference is issued
- **AND** the Agent may submit a corrected ChartSpec for a bounded new
  candidate

#### Scenario: Review state is idempotent and candidate-specific

- **WHEN** the same post-generation event is delivered more than once or a
  review result is retried
- **THEN** the system does not publish duplicate artifacts or apply a review
  result to a different candidate or ChartSpec version
- **AND** the final state remains attributable to the original run and review
  record

#### Scenario: Timeout and retry limits are bounded

- **WHEN** a required review tool, model turn, or candidate retry times out or
  fails repeatedly
- **THEN** the system records a bounded review timeout or retry-exhausted
  state
- **AND** it does not leave an indefinitely pending candidate or publish it as
  verified
