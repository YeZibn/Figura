## MODIFIED Requirements

### Requirement: Independent scatter-point extraction tool

The system SHALL provide an `extract_scatter_points` tool for clean two-
dimensional Cartesian scatter charts. The tool SHALL return a unified
source-image evidence result containing `image_size`, an `orientation`
(`upright`, `oblique`, or `unknown`), a detectable `plot_frame`, x/y axis and
tick calibration evidence, stable series identities, marker geometry, bounded
confidence, and warnings. Each series SHALL include a stable identifier, a
resolved label when available, a color or stable fallback identity, and its
point evidence. Each point SHALL include a stable identifier, source-image
`x_px`/`y_px`, bounded appearance evidence, and calibrated numeric `x`/`y`
values only when both axis transforms meet the declared support, residual, and
confidence thresholds. The result MAY retain pixel-only points when semantic
calibration or series association is unavailable.

The tool SHALL infer the plot frame and axis directions from visible axes,
ticks, grid or marker evidence rather than treating a fixed proportional crop
as ground truth. It SHALL preserve frame, axis, tick, and point geometry in
source-image coordinates, support clean upright charts and small affine
rotations of flat two-dimensional charts, and report fit support, residuals, or
confidence for materially uncertain calibration. Color-distinguished series
and shared coordinates SHALL remain separate when the source evidence supports
that distinction.

The tool SHALL preserve partial pixel evidence for incomplete OCR, missing
axes, ambiguous legends, dense markers, or unsupported perspective/3D styling.
It SHALL not fabricate numeric values from image position alone. Missing,
malformed, unauthorized, unsupported, or non-scatter inputs SHALL return a
bounded structured error or inspectable partial evidence without exposing an
internal local source path or raising an uncaught exception.

#### Scenario: Clean upright scatter points are calibrated

- **WHEN** `extract_scatter_points` is called with a clean upright scatter
  chart containing distinguishable markers, readable numeric axes, and known
  points
- **THEN** the result contains one stable series entry per resolved color
  series and one point entry per reliably visible marker
- **AND** each point has a stable ID, source-image pixel coordinates, bounded
  appearance evidence, and calibrated x/y values within the declared fixture
  tolerance
- **AND** the result contains an inferred plot frame and axis transforms with
  support, residual, and confidence metadata

#### Scenario: Multiple scatter series preserve identity

- **WHEN** a clean scatter chart contains multiple color-distinguished series
  with a legend and overlapping x coordinates
- **THEN** the result contains one series entry per reliably detected series
- **AND** points from different series are not merged solely because their
  coordinates overlap
- **AND** each series carries its legend label when reliably associated, or a
  stable color-based identity with an explicit association warning

#### Scenario: Rotated scatter geometry remains source-aligned

- **WHEN** `extract_scatter_points` is called with a flat scatter chart rotated
  by a small affine angle within the supported range
- **THEN** the result reports `orientation: "oblique"` and retains frame, axis,
  and point positions in source-image coordinates
- **AND** calibrated values are produced only when the rotated axis transforms
  satisfy the declared support, residual, and confidence thresholds
- **AND** ambiguous orientation or excessive residual lowers confidence and
  produces a warning rather than silently dropping points

#### Scenario: Partial calibration remains inspectable

- **WHEN** point geometry is detected but one or both axes cannot be calibrated
  reliably
- **THEN** the result preserves pixel points, appearance evidence, and any
  partial series association
- **AND** it omits semantic x/y values unless both axes are reliable
- **AND** it reports a warning identifying the missing or insufficient
  calibration

#### Scenario: Unsupported or non-scatter geometry remains bounded

- **WHEN** the image contains strong perspective distortion, 3D styling, a
  filled or line-only graphic, or no reliable scatter point population
- **THEN** the tool returns reliable partial point evidence or an empty series
  and points collection
- **AND** it includes a material warning naming the unsupported or ambiguous
  condition
- **AND** it does not fabricate a frame, semantic coordinates, or series
  associations
- **AND** any generated overlay preserves the source dimensions and marks the
  uncertainty

#### Scenario: Missing or malformed input is bounded

- **WHEN** `extract_scatter_points` receives a missing, unauthorized,
  malformed, or non-image input
- **THEN** it returns a structured error without exposing a local source path
  or producing a visual artifact
- **AND** no uncaught exception escapes into the agent loop

### Requirement: Scatter overlap, size, and outlier evidence is explicit

The scatter sensor SHALL preserve bounded evidence about point size, opacity,
nearby or overlapping markers, dense sampling, local occlusion, and potential
outliers when those properties can be observed. It SHALL distinguish a
reliably counted point from a merged, oversized, or occluded point, report
unresolved cases in warnings or confidence metadata, and SHALL not silently
discard a potential outlier or claim a complete point count from incomplete
evidence.

#### Scenario: Overlapping markers are surfaced

- **WHEN** multiple markers overlap or cannot be separated at the source
  resolution
- **THEN** the result preserves the visible cluster or merged-point evidence
  with stable IDs where possible
- **AND** it reports the affected count or association as uncertain in warnings
  or confidence metadata rather than claiming a precise point count

#### Scenario: Marker appearance does not become fabricated data

- **WHEN** point size or opacity differs between markers but the image does not
  provide a reliable quantitative encoding for that appearance
- **THEN** the result retains the observed size or opacity evidence when
  available
- **AND** it does not convert those appearance differences into unverified
  numeric fields in the semantic dataset

#### Scenario: Dense or occluded evidence remains partial

- **WHEN** markers are dense, locally occluded, anti-aliased into one region,
  or separated only by uncertain color evidence
- **THEN** the result retains reliable components and bounded partial counts
- **AND** it marks missing, merged, or uncertain regions through warnings or
  reduced confidence
- **AND** it does not fabricate hidden points or semantic values

#### Scenario: Potential outliers remain available for review

- **WHEN** one or more points are far from the dominant spatial population
- **THEN** the result retains those points with their normal calibrated or
  pixel-only coordinates
- **AND** it marks the potential outlier status as bounded evidence or a warning
- **AND** the agent can choose whether to include them when assembling a
  ChartSpec

### Requirement: Scatter confidence and visual evidence are validated

Every successful scatter sensor result SHALL include bounded confidence
metadata and a warnings collection. The sensor SHALL generate a source-sized
overlay that marks the inferred plot frame, axis evidence, detected points,
stable IDs, series colors, calibration status, merged or overlapping evidence,
and potential-outlier evidence when present. Confidence values SHALL remain
within `[0, 1]`, and low-confidence evidence SHALL remain usable for another
Agent action.

#### Scenario: Complete scatter evidence reports bounded confidence

- **WHEN** a clean scatter fixture has readable axes, distinguishable series,
  separable markers, and reliable frame evidence
- **THEN** the result contains confidence values in `[0, 1]`, calibrated axis
  evidence, stable point identities, and the source-sized overlay
- **AND** the overlay visibly marks the frame, axes, each returned point, and
  its stable identity

#### Scenario: Incomplete scatter evidence produces warnings

- **WHEN** markers are merged, axes are unreadable, frame geometry is
  ambiguous, or a series association is unresolved
- **THEN** the result preserves reliable point evidence and reports a bounded
  warning naming the affected uncertainty
- **AND** it does not present the incomplete result as a certain complete
  dataset

#### Scenario: Generated scatter evidence is model-visible

- **WHEN** the scatter sensor returns structured data and a valid overlay
- **THEN** the existing Agent visual-observation path presents the overlay on
  the next model turn while keeping the structured result available
- **AND** preview and observation transport behavior remains unchanged

### Requirement: Scatter restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
scatter chart through the normal authorized attachment path, to use scatter
evidence, OCR, visual inspection, assemble a coordinate-based scatter
ChartSpec with axes, and independently validate it. The infrastructure MUST
NOT force a fixed scatter-tool sequence or require ChartSpec output for
descriptive image questions.

#### Scenario: Agent restores a clean scatter chart

- **WHEN** the user attaches a clean scatter chart and asks for its underlying
  data
- **THEN** the Agent can choose `extract_scatter_points`, visual inspection,
  OCR, `assemble_spec`, and `validate_spec` in an order it determines
- **AND** the resulting dataset preserves resolved series identities and
  calibrated x/y coordinates when reliable
- **AND** uncertain or pixel-only points remain explicitly retained or flagged
  before semantic assembly

#### Scenario: Scatter ChartSpec requires valid Cartesian axes

- **WHEN** the Agent assembles a scatter result with coordinate points but
  missing or invalid Cartesian axes
- **THEN** `validate_spec` returns located issues without crashing
- **AND** a corrected result with valid x/y axes can pass independently

#### Scenario: Descriptive scatter question does not require restoration

- **WHEN** the user asks a descriptive question about a scatter image rather
  than requesting structured data
- **THEN** the Agent can answer without invoking the scatter sensor or
  assembling a ChartSpec
