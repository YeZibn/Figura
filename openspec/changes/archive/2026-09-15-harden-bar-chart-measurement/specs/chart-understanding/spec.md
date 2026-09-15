## MODIFIED Requirements

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
two-dimensional bar charts and returns a unified, orientation-independent
geometry result. A successful result SHALL include `image_size`, `orientation`
(`vertical`, `horizontal`, `oblique`, or `unknown`), `bar_mode`
(`single`, `grouped`, `stacked`, or `unknown`), a `plot_area` when detectable,
a fitted `baseline` when reliable, series evidence, bars, bounded confidence,
and warnings. Each bar SHALL include a stable `id`, `category_index` when
available, `series_id` when available, `geometry` with `bbox_px` and
`polygon_px`, and `measure` with signed `value_length_px` and normalized
`ratio`. Stacked segments MAY include a `stack` object with their segment index
and total stack length.

The tool SHALL infer the zero baseline from visible chart evidence or shared
bar edges rather than treating a fixed heuristic crop boundary as the baseline.
The baseline SHALL be represented by source-image pixel endpoints, fit residual,
and confidence. The tool SHALL support vertical and horizontal positive bars,
single and grouped bars, supported stacked bars, and small affine rotations of
flat two-dimensional charts. Positive and negative bars SHALL use the signed
value-axis measurement when the zero baseline is reliably detected.

The tool SHALL use one inclusive/exclusive coordinate convention for detection,
serialized geometry, and generated overlays. The generated overlay SHALL mark
each returned bar, its stable identity, the fitted baseline or stack
boundaries, and any material uncertainty while preserving source dimensions.
The legacy fields `baseline_y`, `h_px`, `stacked`, per-bar `series`, flat
per-bar `bbox`, flat per-bar `ratio`, and `stack_total_h_px` SHALL NOT be
emitted by the new result contract.

#### Scenario: Upright single-series bars use the real zero baseline

- **WHEN** `measure_bars` is called with a clean upright single-series chart
  whose bars share a visible zero axis
- **THEN** the result returns one unified bar entry per visible bar
- **AND** each bar's `measure.ratio` matches the source value ratio within 10%
  relative tolerance
- **AND** `baseline.points_px` overlaps the actual zero axis and bar bottoms
  within the declared pixel residual
- **AND** the result does not emit any legacy flat geometry fields
- **AND** the overlay visibly aligns the baseline and bar polygons with the
  source image

#### Scenario: Rotated vertical bars preserve all candidates

- **WHEN** `measure_bars` is called with a flat vertical bar chart rotated by a
  small affine angle within the supported range
- **THEN** the result preserves the true bar count instead of filtering bars
  solely because their bottom pixels have different y coordinates
- **AND** the baseline contains two source-image endpoints describing the
  oblique zero axis
- **AND** each bar contains polygon geometry and a value-axis length
- **AND** a large fit residual or ambiguous orientation becomes a warning and
  lowers confidence rather than silently dropping bars

#### Scenario: Horizontal bars use the same contract

- **WHEN** `measure_bars` is called with a clean horizontal bar chart
- **THEN** `orientation` is `horizontal`
- **AND** the baseline is represented as a vertical source-image line
- **AND** each bar's `measure.value_length_px` is measured along the horizontal
  value axis rather than taken from its bounding-box height
- **AND** category and series associations remain available when detectable

#### Scenario: Positive and negative bars share a zero baseline

- **WHEN** `measure_bars` is called with a clean chart containing positive,
  negative, or mixed-sign bars and a reliably visible zero axis
- **THEN** each returned bar preserves the sign of `measure.value_length_px`
- **AND** ratios are normalized using absolute value-axis lengths
- **AND** bars extending in opposite directions are not merged solely because
  they share the zero baseline
- **AND** ambiguous zero-axis evidence is reported as a warning without
  fabricating signed measurements

#### Scenario: Grouped bars retain category and series distinctions

- **WHEN** `measure_bars` is called with a clean grouped bar chart containing
  multiple color-distinguished series
- **THEN** every returned bar has a stable identifier, category index, and
  series identifier when the association is detectable
- **AND** adjacent bars are not merged solely because they share a baseline
- **AND** the overlay marks individual bar polygons and series identities
  when available

#### Scenario: Stacked bars expose segment and total evidence

- **WHEN** `measure_bars` is called with a clean stacked bar chart whose
  segments have distinguishable colors
- **THEN** the result returns separable segments with their parent category
  and optional stack index
- **AND** each segment retains its value-axis length while its `stack` object
  exposes the total stack geometry when reliable
- **AND** unresolved series or segment associations are reported as warnings
  rather than silently presented as certain

#### Scenario: Unsupported perspective or 3D bars remain bounded

- **WHEN** the image contains strong perspective distortion, 3D bars, or an
  orientation that cannot be reliably classified
- **THEN** the tool returns only reliable partial geometry or an empty bars list
- **AND** it includes a material warning naming the unsupported or ambiguous
  condition
- **AND** it does not fabricate a baseline, signed value length, or semantic
  ratio
- **AND** any generated overlay preserves the source image and marks the
  uncertainty

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an image containing no reliable bars
- **THEN** the result returns an empty `bars` list rather than an exception
- **AND** baseline and plot geometry are absent or null
- **AND** the generated overlay preserves the source dimensions and indicates
  that no reliable bars were detected

#### Scenario: Missing image reports a structured error

- **WHEN** `measure_bars` is called with a path or authorized attachment that
  cannot be resolved to an image
- **THEN** the result is a bounded structured error naming only the failure
- **AND** no visual artifact is produced
- **AND** no uncaught exception escapes into the agent loop
