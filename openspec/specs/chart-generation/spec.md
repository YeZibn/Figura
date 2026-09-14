# chart-generation Specification

## Purpose

Provide a deterministic, validated reverse path that turns Figura's shared ChartSpec data into bounded chart artifacts that an Agent and a user can inspect and reuse.

## Requirements

### Requirement: Valid ChartSpec produces a bounded chart artifact

The system SHALL accept a semantically valid ChartSpec and produce a chart
artifact for bar, line, pie, and scatter chart types. The artifact SHALL
represent the supplied title, labels, series distinctions, and dataset without
inventing, silently dropping, or silently reclassifying semantic data. A
missing categorical value SHALL NOT be rendered as an actual zero. Declared
numeric axis ranges SHALL either be applied to the corresponding axis or be
rejected before rendering. User-visible text containing Chinese characters
SHALL be rendered with a compatible CJK font when one is available, and the
output SHALL use a supported image media type and remain within configured
size and dimension limits.

The generation-facing validation operation and rendering operation SHALL apply
the same structural and chart-type semantic rules. A successful rendering
result SHALL include bounded validation status for semantic, layout, and
artifact checks; a failed check that makes the chart unsafe or semantically
ambiguous SHALL prevent publication of the chart artifact.

#### Scenario: Cartesian ChartSpec is rendered with faithful data

- **WHEN** a valid bar, line, or scatter ChartSpec is submitted for rendering
- **THEN** the system produces an image artifact with the declared chart type,
  title and available axis labels
- **AND** the plotted values, point count, category order, and series
  distinctions correspond to the ChartSpec dataset
- **AND** any declared numeric axis ranges are reflected in the rendered axes
- **AND** Chinese titles, axis labels, tick labels, legends, and data labels
  remain visibly renderable when a compatible CJK font is available

#### Scenario: Missing grouped-bar data is not treated as zero

- **WHEN** a grouped bar ChartSpec declares a category set but a series has no
  value for one of those categories
- **THEN** the system returns a located semantic validation issue and produces
  no chart artifact unless the missing value is explicitly represented by a
  supported missing-data convention
- **AND** it does not publish a zero-height bar that implies an observed zero

#### Scenario: Pie ChartSpec is rendered without axes

- **WHEN** a valid pie ChartSpec contains non-negative categorical values and
  no axes
- **THEN** the system produces an image artifact whose sectors correspond to
  the categories and values
- **AND** the artifact exposes enough legend or label metadata to associate
  each sector with its category
- **AND** Chinese category labels and percentages remain visibly renderable
  when a compatible CJK font is available

#### Scenario: Multi-series data remains distinct

- **WHEN** a valid ChartSpec contains points assigned to multiple series
- **THEN** the generated chart preserves the series distinction in its visual
  encoding and bounded artifact metadata
- **AND** points are not merged solely because they share a category or axis

#### Scenario: Invalid ChartSpec is rejected before rendering

- **WHEN** a ChartSpec is missing required axes, contains invalid points,
  unsupported values, an invalid pie dataset, duplicate categorical points,
  or an invalid numeric axis range
- **THEN** the system returns a bounded structured validation error
- **AND** it produces no chart artifact

#### Scenario: Validation tools agree on generation eligibility

- **WHEN** the same ChartSpec is passed to the generation-facing validation
  operation and the rendering operation
- **THEN** both operations apply the same semantic eligibility rules
- **AND** a spec accepted for rendering is not rejected later for a rule that
  the standalone validation operation omitted

### Requirement: Chinese font availability is diagnosable

The rendering operation SHALL allow a caller to provide a font path override
and SHALL search supported system font families when no override is provided.
When no compatible CJK font can be resolved, the system SHALL still preserve
the existing bounded rendering behavior where possible, while returning an
explicit bounded warning or status that identifies the fallback condition.

#### Scenario: Configured font override is available

- **WHEN** a caller provides a readable supported font path
- **THEN** the renderer uses that font for all generated chart text
- **AND** the result metadata identifies the resolved font as configured

#### Scenario: System CJK font is resolved

- **WHEN** no font override is provided and a supported system CJK font exists
- **THEN** the renderer uses the discovered font for all generated chart text
- **AND** the result metadata identifies the resolved font as system-provided

#### Scenario: No CJK font is available

- **WHEN** neither the configured path nor supported system font families can
  provide a compatible CJK font
- **THEN** the renderer returns a bounded fallback warning or status
- **AND** it does not silently claim that Chinese text was rendered correctly

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
- **AND** the Agent must complete the required semantic review before
  claiming that the generated chart is a verified result

#### Scenario: Agent chooses its review evidence

- **WHEN** a generated chart candidate is pending review
- **THEN** the Agent may choose OCR, chart sensors, visual inspection, or a
  revised ChartSpec in any order supported by the available tools
- **AND** the system preserves the review gate even when the Agent changes
  tools or retries the candidate

#### Scenario: Agent inspects generated visual evidence

- **WHEN** a chart-rendering tool returns a valid visual payload
- **THEN** the Agent can receive the generated chart as attributed visual
  evidence on a later model turn and may accept it, retry it, or ignore it
- **AND** the structured chart metadata remains available independently

#### Scenario: Rendering failure is recoverable

- **WHEN** rendering fails because the input is invalid or a configured output
  limit is exceeded
- **THEN** the tool returns a bounded structured error or warning
- **AND** the Agent run remains able to revise the request or provide a text
  answer without an uncaught renderer exception

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
byte count, dimensions, and the identity of the ChartSpec version it
represents. A published chart SHALL additionally expose its opaque artifact
reference, review status, and bounded review diagnostics. Artifact metadata
SHALL NOT contain local source paths, credentials, raw provider payloads, or
embedded image bytes. Generated output SHALL remain distinguishable from
temporary model-observation images.

#### Scenario: Candidate output is attributable but not final

- **WHEN** rendering produces a chart that passes the applicable deterministic
  renderer and artifact checks but still requires semantic review
- **THEN** the result identifies the output as a review-pending candidate
- **AND** it includes bounded references that associate the candidate with the
  current run and ChartSpec version
- **AND** it does not expose the candidate as a verified final artifact

#### Scenario: Generated output metadata is safe

- **WHEN** a candidate passes all required checks
- **THEN** the published result contains bounded metadata and an opaque
  artifact reference suitable for Gateway and desktop-client retrieval
- **AND** the JSON result contains no raw image bytes or local filesystem path
- **AND** the metadata identifies whether the result was verified cleanly or
  published with an explicit warning

#### Scenario: Pending or failed candidates are not published

- **WHEN** a candidate has pending, failed, expired, or timed-out review state
- **THEN** it cannot be retrieved through the final generated-chart artifact
  route
- **AND** its bounded failure state remains attributable to the run without
  exposing image bytes or local paths

#### Scenario: Output limits and artifact validity are enforced

- **WHEN** the rendered image exceeds the configured byte or dimension limit
  , cannot be fully decoded as the declared image type, or fails an artifact
  integrity check
- **THEN** the system rejects or bounds the output with an explicit reason
- **AND** it does not publish a partial, malformed, or unverified artifact

### Requirement: Rendered chart undergoes a deterministic quality audit

After a ChartSpec has been rendered and before the generated artifact is
returned, the system SHALL audit the in-memory chart and encoded image. The
audit SHALL check that the rendered artists cover the requested data and that
visible titles, labels, tick labels, annotations, legends, and chart content
fit within the fixed output canvas. Layout-only findings MAY be returned as
bounded warnings when the chart remains usable; semantic fidelity failures,
severe clipping, or unreadable output SHALL fail the generation.

#### Scenario: Rendered artists cover the ChartSpec

- **WHEN** a ChartSpec passes pre-render validation and the renderer creates a
  figure
- **THEN** the audit verifies chart-type-specific artist counts and values,
  including bars, line or scatter points, pie sectors, categories, and series
- **AND** a mismatch produces a located validation failure and no published
  chart artifact

#### Scenario: Visible content stays within the canvas

- **WHEN** the renderer has laid out a chart containing titles, axes, labels,
  annotations, or legends
- **THEN** the audit measures their final rendered bounds after a canvas draw
- **AND** content that is clipped or materially outside the fixed canvas
  produces a structured layout failure or warning according to configured
  severity

#### Scenario: Usable layout warning remains explicit

- **WHEN** a chart is renderable but has dense labels, a crowded legend, or
  another bounded readability concern that does not invalidate its data
- **THEN** the system returns the chart with validation status `warning`
- **AND** the result identifies the concern without claiming an unqualified
  validation pass

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
- **THEN** the candidate transitions to a verified or warning publication
  state according to its bounded diagnostics
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
