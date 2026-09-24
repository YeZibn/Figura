## MODIFIED Requirements

### Requirement: Shared Cartesian layout and series evidence

Cartesian chart sensors SHALL expose a common evidence envelope containing the
source image dimensions, a plot-area bounding box when detected, axis labels or
tick calibration evidence when available, resolved legend entries, and series
identities. When a validated layout context is available, the envelope SHALL
also identify the accepted layout context, its orientation, region roles, and
validation confidence. Missing or ambiguous fields SHALL be represented as
absent or uncertain values rather than invented values. The envelope SHALL be
sufficient for the agent to associate geometry, OCR, axes, and legend evidence
without requiring one chart detector to invoke another.

The shared layout SHALL distinguish the measurement frame from surrounding
annotation regions. It SHALL support date and categorical tick labels as
ordered positional evidence even when they cannot be converted to numeric
ChartSpec coordinates. Model-provided layout hints SHALL remain advisory until
they pass deterministic validation.

#### Scenario: Clean axes and legend are correlated

- **WHEN** a sensor processes a clean Cartesian fixture with visible axes and a
  legend
- **THEN** the structured result identifies the common plot area and includes
  the available axis and legend evidence
- **AND** the series identifiers used in geometry and overlays are consistent
  across the returned evidence

#### Scenario: Validated model layout is shared by Cartesian sensors

- **WHEN** the Agent has accepted a layout context for a bar, line, or scatter
  chart
- **THEN** each applicable sensor uses the same source-image frame and region
  roles in its evidence envelope
- **AND** title, legend, tick labels, and data annotations outside the frame do
  not become mark geometry solely because they are dark or colorful

#### Scenario: Date and categorical ticks remain positional evidence

- **WHEN** a Cartesian chart uses ordered date or category labels instead of
  numeric X-axis values
- **THEN** the result preserves their text, source positions, and ordering when
  detectable
- **AND** it omits numeric X values unless a reliable semantic mapping exists
- **AND** it reports the missing numeric calibration explicitly

#### Scenario: Partial layout evidence is retained

- **WHEN** a chart has detectable geometry but an axis, legend, model layout
  hint, or plot boundary is partially occluded or unreadable
- **THEN** the sensor returns the reliable geometry it can measure
- **AND** marks the missing or conflicting association in warnings or
  confidence metadata
- **AND** the result remains valid JSON suitable for another agent action

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
calibrated. Date or categorical X labels MAY be retained as ordered labels and
pixel anchors without being converted to fabricated numeric values.

The tool SHALL consume an accepted layout context when one is supplied and
SHALL keep the measurement frame separate from legend, tick-label, and data-
annotation regions. It SHALL infer or validate axis directions from visible
axes, ticks, grid or trace evidence rather than treating a fixed crop boundary
as ground truth. It SHALL preserve trace and axis geometry in source-image
coordinates, support small affine rotations of flat two-dimensional charts,
and report fit residuals or confidence for materially uncertain frame and
calibration evidence. A trace crossing, overlap, or color-preserving series
intersection SHALL NOT merge distinct series solely because their pixels are
nearby.

The tool SHALL distinguish marker-derived points from points sampled at
reliable X-axis anchors. It SHALL NOT treat arbitrary pixel-density peaks,
unanchored local extrema, legend fragments, annotations, or a continuous
trace as confirmed data points. When no reliable sampling anchor exists, it
SHALL preserve trace geometry and report the sampling limitation instead of
claiming a complete point count.

The generated overlay SHALL preserve source dimensions and mark the inferred
or accepted frame, axis evidence, measured traces, confirmed points, stable
identities, calibration status, and material uncertainty. Invalid, unsupported,
or ambiguous inputs SHALL produce bounded structured errors or partial evidence
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
  markers but with readable numeric, date, or categorical X-axis ticks or
  equivalent ordered anchors
- **THEN** the result returns continuous trace geometry
- **AND** it emits points only at reliable anchors using `source: "tick_sample"`
  or an equivalent explicit anchor source
- **AND** it does not create extra points from unanchored density peaks or
  local slope changes
- **AND** the result reports any unresolved sampling limitation in warnings

#### Scenario: Model-guided framing excludes rotated labels

- **WHEN** a chart has a validated layout context with a horizontal plot frame
  and vertically rotated date labels outside that frame
- **THEN** the line trace and axis geometry are measured inside the accepted
  frame
- **AND** rotated labels, legend swatches, and label text do not create axis
  slopes, trace fragments, or marker points
- **AND** the result reports a material warning if the pixel evidence still
  conflicts with the layout context

#### Scenario: Multiple series remain distinct through crossings

- **WHEN** a line chart contains multiple color-distinguished series that
  cross, overlap, or share X positions
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
