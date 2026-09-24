## MODIFIED Requirements

### Requirement: Line-series extraction tool

The system SHALL provide an `extract_line_series` tool for clean two-
dimensional single-series and multi-series line charts. The tool SHALL return a
unified source-image evidence result containing `image_size`, an `orientation`
(`upright`, `oblique`, or `unknown`), a detectable `plot_frame`, x/y axis and
tick calibration evidence, stable series identities, ordered trace geometry,
bounded confidence, and warnings. Each series SHALL include a stable `id`, a
resolved label when available, a color or stable fallback identity, and its
trace evidence. Each confirmed point SHALL include a stable identifier, a
source-image pixel position, a point source (`marker` or `tick_sample`), and
calibrated numeric `x` and `y` values only when both axes are reliably
calibrated. The result MAY retain trace geometry without semantic points when
sampling or calibration is unavailable.

The tool SHALL infer the plot frame and axis directions from visible axes,
ticks, grid or trace evidence rather than treating a fixed crop boundary as
ground truth. It SHALL preserve trace and axis geometry in source-image
coordinates, support small affine rotations of flat two-dimensional charts,
and report fit residuals or confidence for materially uncertain frame and
calibration evidence. A trace crossing, overlap, or color-preserving series
intersection SHALL NOT merge distinct series solely because their pixels are
nearby.

The tool SHALL distinguish marker-derived points from points sampled at
reliable x-axis anchors. It SHALL NOT treat arbitrary pixel-density peaks,
unanchored local extrema, or a continuous trace as confirmed data points. When
the chart uses categorical x labels without a reliable numeric mapping to the
supported ChartSpec coordinate model, the tool SHALL preserve the labels or
pixel evidence and report a warning instead of fabricating numeric x values.

The generated overlay SHALL preserve source dimensions and mark the inferred
frame, axis evidence, measured traces, confirmed points, stable identities,
calibration status, and material uncertainty. Invalid, unsupported, or
ambiguous inputs SHALL produce bounded structured errors or partial evidence
without uncaught exceptions or fabricated semantic values.

#### Scenario: Upright marker line points are returned

- **WHEN** `extract_line_series` is called with a clean upright single-series
  line chart containing visible markers, readable numeric axes, and known
  points
- **THEN** the result contains one stable series and one confirmed point per
  reliably visible marker
- **AND** each point contains source-image coordinates, `source: "marker"`,
  and calibrated numeric x/y values within the declared fixture tolerance
- **AND** the fitted plot frame and axis calibration evidence are returned with
  bounded residual or confidence metadata
- **AND** the source-sized overlay marks the trace, points, and point IDs

#### Scenario: Markerless lines use reliable x-axis anchors

- **WHEN** `extract_line_series` is called with a clean line chart without
  markers but with readable numeric x-axis ticks or equivalent ordered anchors
- **THEN** the result returns continuous trace geometry
- **AND** it emits points only at reliable anchors using `source: "tick_sample"`
- **AND** it does not create extra points from unanchored density peaks or
  local slope changes
- **AND** the result reports any unresolved sampling limitation in warnings

#### Scenario: Multiple series remain distinct through crossings

- **WHEN** a line chart contains multiple color-distinguished series that
  cross, overlap, or share x positions
- **THEN** the result contains one series entry per reliably resolved trace
- **AND** points and trace fragments from different series are not merged
  solely because their pixels are adjacent or intersect
- **AND** each series carries its legend label when reliably associated, or a
  stable color-based identity with an explicit association warning

#### Scenario: Rotated line charts preserve source geometry

- **WHEN** `extract_line_series` is called with a flat line chart rotated by a
  small affine angle within the supported range
- **THEN** the result reports `orientation: "oblique"` and retains trace,
  frame, axis, and point positions in source-image coordinates
- **AND** calibrated values are produced only when the rotated frame and both
  axis transforms meet the declared confidence threshold
- **AND** large frame residual or ambiguous orientation lowers confidence and
  produces a warning rather than silently dropping the trace

#### Scenario: Incomplete calibration preserves pixel evidence

- **WHEN** line geometry is detected but one or both axes cannot be calibrated
  reliably
- **THEN** the result preserves ordered pixel trace geometry and any reliable
  marker or anchor points
- **AND** it omits semantic x/y values for points whose calibration is not
  reliable
- **AND** it reports a warning identifying the missing calibration
- **AND** the generated overlay remains source-sized and inspectable

#### Scenario: Positive, negative, and zero-crossing values retain sign

- **WHEN** a clean calibrated line chart contains values above, below, or
  crossing the y=0 level
- **THEN** calibrated point y values preserve their signed numeric values
- **AND** the result does not infer sign from image height alone when the zero
  level is not established by axis or tick evidence
- **AND** ambiguous zero calibration is reported as a warning without
  fabricating signed values

#### Scenario: Dense, merged, or occluded traces remain bounded

- **WHEN** the chart contains dense sampling, marker overlap, local occlusion,
  dashed or fragmented evidence, or a trace that cannot be separated reliably
- **THEN** the result retains reliable trace fragments and confirmed points
- **AND** it marks merged, missing, or uncertain sections through warnings or
  bounded confidence
- **AND** it does not claim a complete point count or fabricate missing values

#### Scenario: Unsupported perspective or non-line geometry remains inspectable

- **WHEN** the image contains strong perspective distortion, 3D styling,
  filled-area geometry, or no reliably classifiable line trace
- **THEN** the tool returns reliable partial trace evidence or an empty series
  collection
- **AND** it includes a material warning naming the unsupported or ambiguous
  condition
- **AND** it does not fabricate a frame, semantic point values, or series
  associations
- **AND** any generated overlay preserves the source dimensions and marks the
  uncertainty

#### Scenario: Invalid line input reports a structured error

- **WHEN** `extract_line_series` receives a missing, unauthorized, malformed,
  or non-image input
- **THEN** it returns a bounded structured error without exposing an internal
  local source path or producing a visual artifact
- **AND** no uncaught exception escapes into the agent loop
