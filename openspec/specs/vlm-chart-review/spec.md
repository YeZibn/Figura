# vlm-chart-review Specification

## Purpose

为生成图表提供一次自动、统一且可追踪的多模态语义审核，使 VLM 能够直接结合原图、ChartSpec 和候选图判断旋转、横向布局、标签关联、数值映射与可读性，而不依赖审核阶段的 OCR、CV 或测量工具。

## Requirements

### Requirement: Semantic chart review is performed by an internal tool-free VLM

For every generated chart candidate whose review policy requires semantic
review, the system SHALL automatically perform one additional multimodal VLM
review call after rendering. The review call SHALL not expose or invoke OCR,
CV, geometry, layout, chart-measurement, or generated-chart review tools, and
the main Agent SHALL not be responsible for deciding whether to invoke it.

#### Scenario: Source-linked candidate is reviewed automatically

- **WHEN** a ChartSpec derived from an authorized source attachment is rendered
  into a candidate image
- **THEN** the system automatically invokes one VLM review call before
  publication
- **AND** the review call has no tools available
- **AND** the candidate remains unpublished until the review result is applied

#### Scenario: Review receives the required visual and structured context

- **WHEN** the internal VLM review call is prepared for a source-linked
  candidate
- **THEN** it receives the authorized source image, the generated candidate
  image, and the immutable ChartSpec represented by the candidate
- **AND** it can distinguish source-versus-candidate comparison from
  candidate-versus-spec comparison
- **AND** local paths, credentials, raw provider payloads, and unrelated
  attachments are not included

#### Scenario: Direct-data candidate has no source-fidelity claim

- **WHEN** a candidate is generated only from user-supplied structured data and
  its policy does not require semantic review
- **THEN** the system does not claim that a source comparison was performed
- **AND** the candidate still passes the applicable structural and encoded
  artifact safety checks before publication

### Requirement: VLM review returns a bounded structured decision

The internal reviewer SHALL return exactly one JSON object with exactly four
top-level fields: `decision`, `confidence`, `checks`, and `issues`. `decision`
SHALL be `pass`, `pass_with_warning`, or `fail`. `confidence` SHALL be a
number in the range 0..1. `checks` SHALL contain exactly
`chart_type`, `orientation`, `layout`, `data_mapping`, `labels`, and
`readability`, with each value equal to `pass`, `warning`, or `fail`.

`issues` SHALL be an array of at most 32 objects. Each issue SHALL contain
non-empty bounded `code`, `location`, and `message` strings and a `severity`
of `warning` or `error`. The review SHALL cover chart type, whole-canvas
rotation, horizontal-versus-vertical orientation, axis direction, category
order, series identity, values or relative geometry, zero-baseline or other
geometric relationships, labels, and readability. Bar, line, pie, and scatter
charts SHALL receive the corresponding chart-specific visual checks.

The decision SHALL be internally consistent: `pass` requires all checks to be
`pass` and no issues; `pass_with_warning` permits no failed check or error and
requires a warning detail; `fail` requires a failed check or error issue. A
critical relationship that cannot be verified SHALL NOT be treated as a pass.
A missing, malformed, ambiguous, extra-field, or out-of-contract response
SHALL NOT be treated as a pass.

#### Scenario: VLM identifies a clean match

- **WHEN** the candidate matches the ChartSpec and, when applicable, the
  source image across the required visual checks
- **THEN** the reviewer returns the exact four-field JSON contract with
  `decision: pass`
- **AND** all six check values are `pass`
- **AND** `issues` is an empty array

#### Scenario: VLM identifies a blocking visual mismatch

- **WHEN** the candidate has a wrong orientation, category order, series
  association, value mapping, label association, baseline relationship, or
  another critical visual mismatch
- **THEN** the reviewer returns `decision: fail`
- **AND** at least one check is `fail` or one issue has `severity: error`
- **AND** the issue identifies the affected ChartSpec field or visual region
  with a bounded explanation
- **AND** the candidate cannot be published

#### Scenario: VLM identifies a non-blocking concern

- **WHEN** the data mapping is credible but the candidate has a bounded
  readability, density, or non-critical visual concern allowed by policy
- **THEN** the reviewer returns `decision: pass_with_warning`
- **AND** no check is `fail` and no issue has `severity: error`
- **AND** at least one check or issue records a warning
- **AND** the warning is retained in the candidate's bounded review metadata
- **AND** publication, if allowed, remains explicitly qualified

#### Scenario: VLM reports an incorrect bar baseline

- **WHEN** a vertical bar chart's bar bottoms do not align with the coordinate
  system's zero baseline, or a horizontal bar chart's bar starts do not align
  with the zero baseline
- **THEN** the reviewer records a layout or data-mapping failure with a
  location such as `candidate.plot_area.zero_baseline`
- **AND** the result has `decision: fail` and an error issue
- **AND** the image bottom or plot-frame edge is not accepted as the baseline
  merely because it is visually closest

#### Scenario: Invalid reviewer output is rejected

- **WHEN** the VLM response is not valid JSON, contains extra top-level fields,
  omits a required field, uses an unknown enum, has an out-of-range confidence,
  violates the decision consistency rules, or contains unbounded issue data
- **THEN** the system records a bounded review failure
- **AND** it does not publish the candidate or infer a pass from free-form text

### Requirement: Review decisions are code-enforced publication transitions

The system SHALL apply the validated VLM decision atomically to the
candidate's review and publication state. Only `pass` MAY transition a
candidate to `published`, and only an allowed `pass_with_warning` MAY
transition it to `published_with_warning`; `fail`, invalid output, timeout,
or unavailable source evidence SHALL transition it to a non-published state.
The main Agent SHALL not be able to override the transition with a final answer
or a model-generated review claim.

#### Scenario: Passing review promotes the candidate

- **WHEN** a candidate's required safety checks pass and its VLM decision is
  `pass`
- **THEN** the candidate becomes verified and published with bounded review
  metadata
- **AND** the Gateway may expose the corresponding final artifact

#### Scenario: Failed review rejects the candidate

- **WHEN** the VLM decision is `fail` or the review cannot be completed
- **THEN** the candidate becomes review-failed, timed-out, or retry-exhausted
  according to the failure cause
- **AND** no final artifact reference is issued
- **AND** a final Agent response cannot describe the candidate as verified or
  published

#### Scenario: Review result cannot be applied to another candidate

- **WHEN** a review result carries a missing, stale, or mismatched candidate
  reference, review reference, or ChartSpec digest
- **THEN** the system rejects the result with a bounded error
- **AND** no other candidate's publication state changes

### Requirement: VLM review failures support bounded correction and retry

When a VLM review fails for a correctable visual or semantic issue, the system
SHALL provide the bounded review diagnostics to the main Agent so it can revise
the ChartSpec and request a new candidate. Review calls and candidate retries
SHALL obey the configured attempt, timeout, and size limits, and an exhausted
limit SHALL produce a terminal non-published state.

#### Scenario: Blocking issue is repaired with a new candidate

- **WHEN** a VLM review rejects a candidate with a correctable issue and retry
  budget remains
- **THEN** the main Agent receives the issue location and bounded explanation
- **AND** it can assemble a corrected ChartSpec and render a new candidate
- **AND** the rejected candidate remains attributable and unpublished

#### Scenario: Review timeout is bounded

- **WHEN** the internal VLM review call exceeds its deadline or fails repeatedly
- **THEN** the system records a bounded timeout or retry-exhausted state
- **AND** it does not leave the candidate indefinitely pending
- **AND** it does not publish the candidate
