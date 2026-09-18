# chart-understanding Specification

## Purpose

Give the agent deterministic sensors and a code-side assembler plus an
independent validator, so it can restore clean annotated Cartesian charts to a
valid ChartSpec through its own observe-reason-act loop, with the VLM doing
semantic association and tools doing measurement.

## Requirements

### Requirement: Common chart observation envelope

The bar, line, scatter, and pie observation tools SHALL expose a common
evidence envelope alongside their chart-specific measurements. The envelope
SHALL contain source-image size, a coordinate-system-aware frame, legend and
series association evidence when available, bounded confidence, and
warnings. Source-image geometry SHALL use one coordinate convention across
all four tools. Missing or ambiguous evidence SHALL remain null, partial, or
uncertain rather than being fabricated.

The envelope SHALL distinguish common evidence from chart-specific geometry.
Bar geometry, line traces, scatter markers, and pie sectors MAY retain their
specialized fields, but those fields SHALL reference stable evidence and
series identifiers from the common envelope when applicable.

#### Scenario: All supported chart tools expose common evidence

- **WHEN** the Agent invokes a successful bar, line, scatter, or pie
  observation tool
- **THEN** the result contains the common source-image, frame, association,
  confidence, and warning evidence
- **AND** the result retains the chart-specific measurements needed for the
  corresponding chart type
- **AND** the result remains valid JSON suitable for another Agent action

#### Scenario: Partial common evidence remains inspectable

- **WHEN** a chart has detectable geometry but its frame, legend, OCR, or
  series association is incomplete
- **THEN** the result preserves the reliable chart-specific geometry
- **AND** the missing evidence is represented as null, partial, or uncertain
- **AND** the result reports the affected uncertainty in warnings or confidence

#### Scenario: Source geometry is consistent across chart types

- **WHEN** a supported chart is translated, resized, or subjected to a
  supported flat-image rotation
- **THEN** all serialized points, lines, polygons, frames, and labels remain
  in the original source-image coordinate system
- **AND** the generated visual evidence uses the same coordinates

### Requirement: Coordinate models are pluggable and explicit

The observation infrastructure SHALL represent the coordinate model used by a
chart explicitly without forcing every chart into one coordinate system.
Bar, line, and scatter observations SHALL use a Cartesian two-dimensional
model when their axes are supported. Pie observations SHALL use a polar
two-dimensional model with circular or angular evidence. A result with no
reliable coordinate model SHALL remain inspectable with pixel geometry and a
bounded unknown status.

Coordinate evidence SHALL separate source-image geometry from semantic value
calibration. Numeric values SHALL be emitted only when the selected model's
axis or angular calibration satisfies its support, residual, and confidence
thresholds. Unsupported perspective, 3D, elliptical, or otherwise invalid
geometry SHALL be reported as partial or unsupported rather than silently
normalized into a different model.

#### Scenario: Cartesian and polar charts retain different semantics

- **WHEN** the tools process a clean bar, line, scatter, and ordinary pie
  fixture
- **THEN** the first three results identify Cartesian axes and transforms
- **AND** the pie result identifies polar center, radius, and angular evidence
- **AND** the pie result does not fail because Cartesian axes are absent

#### Scenario: Calibration failure does not erase geometry

- **WHEN** a coordinate model is detected but one or more numeric transforms
  cannot be calibrated reliably
- **THEN** the result preserves source-image geometry and model evidence
- **AND** it omits unsupported semantic values
- **AND** it reports the failed calibration through bounded warnings or
  confidence metadata

#### Scenario: Unsupported geometry remains bounded

- **WHEN** an image contains strong perspective, 3D styling, or a coordinate
  shape outside the supported model
- **THEN** the tool returns reliable partial evidence or an empty chart-specific
  collection
- **AND** it identifies the unsupported condition
- **AND** it does not fabricate a complete coordinate transform or dataset

### Requirement: Chart marks remain independently specialized

The infrastructure SHALL keep chart-mark extraction independent from the
shared evidence and coordinate layers. Bar, line, scatter, and pie detectors
SHALL consume common frame, color, text, and quality evidence without
depending on one another or importing another chart detector's private
helpers. The common layer SHALL NOT require a fixed Agent-facing tool order.

Each detector SHALL preserve its own observable semantics: bar baselines and
stacks, line traces and anchored points, scatter marker and overlap evidence,
or pie sectors and label associations. Shared series and legend identifiers
SHALL be usable by these specialized measurements without converting one mark
type into another.

#### Scenario: A detector can operate with partial shared evidence

- **WHEN** a mark detector receives a frame, OCR, color, or legend result that
  is incomplete
- **THEN** it returns the reliable mark evidence it can establish
- **AND** it does not require another chart detector to complete its result
- **AND** the result marks the missing dependency as uncertainty rather than
  raising an uncaught exception

#### Scenario: Series identity survives specialized geometry

- **WHEN** multiple color-distinguished series are present in a bar, line, or
  scatter chart
- **THEN** each specialized geometry item retains a stable series identifier
- **AND** crossing, overlap, grouping, or stacking does not merge series solely
  because their pixels are close
- **AND** unresolved labels remain explicit rather than invented

#### Scenario: Agent planning remains free

- **WHEN** the user asks for chart restoration or only a descriptive answer
- **THEN** the Agent can choose OCR, visual inspection, a specialized chart
  sensor, assembly, and validation in an order it determines
- **AND** the shared infrastructure does not force every tool or require a
  ChartSpec for descriptive questions

### Requirement: Shared chart quality and visual evidence

Every successful chart observation SHALL expose bounded confidence and
warnings through the common evidence envelope. Confidence values SHALL stay
within `[0, 1]`, and warnings SHALL identify material uncertainty such as
frame ambiguity, calibration failure, unresolved association, merged
geometry, unsupported styling, or incomplete totals. A low-confidence result
SHALL remain usable partial evidence.

The observation infrastructure SHALL provide a source-sized visual evidence
layer for the common frame, coordinate evidence, stable IDs, and material
uncertainty. Chart-specific overlays MAY add bars, traces, markers, sectors,
labels, and baselines, but they SHALL draw from the same serialized source
coordinates instead of re-detecting geometry.

#### Scenario: Complete evidence reports bounded quality

- **WHEN** a clean fixture has complete geometry, coordinate, and association
  evidence
- **THEN** all confidence values are within `[0, 1]`
- **AND** the result includes the common frame and chart-specific overlay
- **AND** the overlay dimensions match the source image

#### Scenario: Ambiguity is visible in data and overlay

- **WHEN** an axis, baseline, legend association, sector boundary, marker
  count, or calibration is ambiguous
- **THEN** the result preserves reliable evidence and emits a material warning
- **AND** confidence is reduced or the affected semantic field is omitted
- **AND** the overlay marks the relevant uncertainty without changing source
  dimensions

#### Scenario: Observation transport remains unchanged

- **WHEN** a sensor returns the common envelope and its source-sized overlay
- **THEN** the existing Agent visual-observation path presents the overlay
  while keeping structured evidence available
- **AND** no new Gateway route or frontend preview protocol is required

### Requirement: Whole-image text extraction tool

The system SHALL provide an `extract_text` tool that runs deterministic OCR on
a whole local image and returns every detected text snippet with its bounding
box and a confidence score. The tool takes no region arguments.
The tool SHALL also produce a generated overlay image that identifies the
detected text regions so the multimodal model can inspect their placement.

#### Scenario: Annotations and labels are returned with visual evidence

- **WHEN** `extract_text` is called with a synthetic bar chart image whose
  value annotations are known
- **THEN** the result contains one entry per printed text with `text`, `bbox`
  (`[x, y, width, height]`), and `confidence` in `[0, 1]`
- **AND** the value annotations appear as their exact printed strings
- **AND** a generated overlay with the source image dimensions visibly marks
  and identifies each returned text region

#### Scenario: Unreadable image reports a structured error

- **WHEN** `extract_text` is called with a path that does not exist
- **THEN** the tool returns `{"error": ...}` naming the path, and never raises
  an uncaught exception into the agent loop
- **AND** the tool produces no visual artifact

#### Scenario: No detected text still produces inspectable evidence

- **WHEN** OCR completes successfully but detects no text
- **THEN** the structured result is empty and the generated overlay preserves
  the source image so the model can inspect the absence of detections

### Requirement: Bar geometry measurement tool

The system SHALL provide a `measure_bars` tool that deterministically detects
two-dimensional bar charts and returns a unified, orientation-independent
geometry result. A successful result SHALL include `image_size`, `orientation`
(`vertical`, `horizontal`, `oblique`, or `unknown`), `bar_mode` (`single`,
`grouped`, `stacked`, or `unknown`), a `plot_area` when detectable, a fitted
`baseline` when reliable, series evidence, bars, bounded confidence, and
warnings. Each bar SHALL include a stable `id`, `category_index` when
available, `series_id` when available, `geometry` with `bbox_px` and
`polygon_px`, and `measure` with signed `value_length_px` and normalized
`ratio`. Stacked segments MAY include a `stack` object with their segment index
and total stack length.

The tool SHALL infer the zero baseline from visible chart evidence or shared
bar edges rather than treating a fixed heuristic crop boundary as the baseline.
The baseline SHALL be represented by source-image pixel endpoints, fit
residual, and confidence. The tool SHALL support vertical and horizontal
positive bars, single and grouped bars, supported stacked bars, and small
affine rotations of flat two-dimensional charts. Positive and negative bars
SHALL use the signed value-axis measurement when the zero baseline is reliably
detected.

The tool SHALL use one half-open source-image coordinate convention for
detection and serialization, converting to inclusive drawing endpoints only in
the overlay. The generated overlay SHALL mark each returned bar, its stable
identity, the fitted baseline or stack boundaries, and material uncertainty
while preserving source dimensions. The legacy fields `baseline_y`, `h_px`,
`stacked`, per-bar `series`, flat per-bar `bbox`, flat per-bar `ratio`, and
`stack_total_h_px` SHALL NOT be emitted.

#### Scenario: Upright single-series bars use the real zero baseline

- **WHEN** `measure_bars` is called with a clean upright single-series chart
  whose bars share a visible zero axis
- **THEN** the result returns one unified bar entry per visible bar
- **AND** each bar's `measure.ratio` matches the source value ratio within 10%
  relative tolerance
- **AND** `baseline.points_px` overlaps the actual zero axis and bar bottoms
  within the declared pixel residual
- **AND** the overlay visibly aligns the baseline and bar polygons with the
  source image

#### Scenario: Rotated vertical bars preserve all candidates

- **WHEN** `measure_bars` is called with a flat vertical bar chart rotated by
  a small affine angle within the supported range
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

- **WHEN** `measure_bars` is called with a clean stacked bar chart whose stack
  segments have distinguishable colors
- **THEN** the result returns separable segments with their parent category
  and optional stack index
- **AND** each segment retains its value-axis length while its `stack` object
  exposes the total stack geometry when reliable
- **AND** unresolved series or segment associations are reported as warnings
  rather than silently presented as certain

#### Scenario: Unsupported perspective or 3D bars remain bounded

- **WHEN** the image contains strong perspective distortion, 3D styling, or an
  orientation that cannot be reliably classified
- **THEN** the tool returns only reliable partial geometry or an empty bars list
- **AND** it includes a material warning naming the unsupported or ambiguous
  condition
- **AND** it does not fabricate a baseline, signed value length, or semantic
  ratio
- **AND** any generated overlay preserves the source image and marks the
  uncertainty

#### Scenario: Non-chart image remains inspectable

- **WHEN** `measure_bars` is called with an image containing no detectable bars
- **THEN** the result returns an empty `bars` list rather than an exception
- **AND** baseline and plot geometry are absent or null
- **AND** the generated overlay preserves the source dimensions and indicates
  that no reliable bars were detected

#### Scenario: Missing image reports a structured error

- **WHEN** `measure_bars` is called with a path or attachment that cannot be
  resolved to an image
- **THEN** the tool returns `{"error": ...}` naming only the bounded failure,
  produces no visual artifact, and never raises an uncaught exception into the
  agent loop

### Requirement: Code-side ChartSpec assembly tool

The system SHALL provide an `assemble_spec` tool that constructs a ChartSpec
from typed arguments (chart type, title, axis labels, points, source) in code
and atomically applies the chart-type, axis, point, range, and generation
constraints before returning its dictionary form; the model never hand-writes
IR JSON and does not need a separate validation tool call for the assembled
result. A failed assembly SHALL return bounded, located issues and SHALL NOT
return a ChartSpec that downstream generation can treat as valid.

#### Scenario: Valid arguments produce a schema-shaped spec

- **WHEN** `assemble_spec` is called with a bar chart type and category/value
  points
- **THEN** the returned dictionary round-trips through `ChartSpec.from_dict`
  and `to_dict` unchanged
- **AND** metadata carries the provided source provenance
- **AND** the returned ChartSpec has passed the same semantic constraints used
  by downstream chart generation

#### Scenario: Malformed points are rejected as structured errors

- **WHEN** `assemble_spec` is called with points lacking required fields or a
  chart type outside the enumeration
- **THEN** the tool returns `{"error": ...}` describing the offending input
  and produces no spec

#### Scenario: Semantic validation failure prevents downstream use

- **WHEN** typed inputs produce an empty dataset, incompatible point shape,
  invalid axis contract, invalid range, or another generation-blocking issue
- **THEN** `assemble_spec` returns bounded located issues through its error
  result
- **AND** it does not return a partially accepted ChartSpec for rendering or
  final structured output

### Requirement: U0 end-to-end restoration through the ReAct loop

The system SHALL enable the agent, given a clean annotated bar chart, clean
single/multi-series line chart, clean pie chart, or clean single/multi-series
scatter chart through the normal image-attachment path and the registered
chart tools, to produce a ChartSpec whose semantic dataset matches the chart's
true values when those values are visually recoverable. The attachment path
needed by local-image tools SHALL be available to the model without the user
repeating it. The multimodal model SHALL be allowed to use its visual
understanding as the first-pass semantic evidence, and OCR, chart sensors, and
layout inspection SHALL be auxiliary evidence selected according to observed
uncertainty. The infrastructure MUST NOT force a fixed tool sequence or
require `inspect_chart_layout` or ChartSpec output for every image turn.

#### Scenario: Clear annotated bar-chart restoration

- **WHEN** the user attaches a synthetic single- or multi-series bar chart with
  readable category and value annotations and asks for the underlying data
- **THEN** the agent may directly use visual understanding and `assemble_spec`
  or may call targeted sensors before assembly
- **AND** the dataset values and series identities equal the ground-truth
  values and identities used to draw the chart

#### Scenario: Freely planned annotated bar-chart restoration

- **WHEN** the user attaches a bar chart with partially uncertain annotations,
  layout, or geometry through the standard agent REPL and asks for the
  underlying data
- **THEN** the agent can choose OCR, bar geometry, layout inspection,
  assembly, and validation tools according to the unresolved evidence
- **AND** the resulting values retain warnings or uncertainty when the
  available evidence cannot resolve them

#### Scenario: Freely planned line-chart restoration

- **WHEN** the user attaches a clean line chart with one or more legend-defined
  series and asks for the underlying data
- **THEN** the agent can combine visual understanding, line-series evidence,
  OCR, layout inspection, assembly, or a retry in any order that it chooses
- **AND** the resulting coordinate points preserve the x ordering, y values,
  and semantic series distinction within the supported fixture tolerance

#### Scenario: Freely planned scatter-chart restoration

- **WHEN** the user attaches a clean single- or multi-series scatter chart with
  readable axes and asks for the underlying data
- **THEN** the agent can combine visual understanding, scatter evidence, OCR,
  layout inspection, assembly, and validation tools without a caller-supplied
  workflow prompt
- **AND** the resulting coordinate points preserve the detected x/y values and
  resolved series distinction within the supported fixture tolerance

#### Scenario: Image question does not require restoration

- **WHEN** the user asks a descriptive question that does not require
  structured chart data
- **THEN** the agent can answer without assembling or validating a ChartSpec

#### Scenario: Conflicting evidence is surfaced before assembly

- **WHEN** annotation values, axis calibration, series colors, layout hints, or
  geometric measurements disagree beyond the reported confidence tolerance
- **THEN** the agent receives structured warnings and visual evidence, and can
  re-examine, switch tools, or preserve an unresolved candidate before
  assembling
- **AND** the final answer does not silently claim unresolved values as certain

### Requirement: Chart tools registered for the agent REPL

The system SHALL register the existing chart tools, the line-series sensor, the
pie-sector sensor, and the scatter-point sensor alongside the built-in tools
when the agent REPL starts, following the existing tool protocol (JSON
observations, structured errors, and optional bounded visual observations).
The model-facing chart tool surface SHALL expose `assemble_spec` as the sole
ChartSpec construction-and-validation gate; internal validation used by
generation or review SHALL NOT be registered as a separate model tool.

#### Scenario: REPL exposes Cartesian, pie, and scatter chart tools

- **WHEN** the `--agent` REPL starts
- **THEN** the tool registry contains `extract_text`, `measure_bars`,
  `extract_line_series`, `extract_pie_slices`, `extract_scatter_points`,
  `assemble_spec`, and `render_chart` in addition to the built-ins
- **AND** the registry does not contain `validate_spec`

### Requirement: Chart sensors use authorized attachments

In the Agent tool registry, `extract_text`, `measure_bars`,
`extract_line_series`, `extract_pie_slices`, and `extract_scatter_points` SHALL
accept an authorized attachment ID resolved through the active session boundary
and SHALL not expose arbitrary local paths in their model-facing schemas or
results. Direct Python path-based sensor compatibility MAY remain available.
Attachment failures SHALL be bounded structured errors without visual artifacts.

#### Scenario: Authorized sensor call

- **WHEN** a registered chart sensor, including the pie and scatter sensors,
  receives a valid attachment ID
- **THEN** it resolves the internal source image, returns its structured result,
  and preserves any source-sized visual overlay

#### Scenario: Unauthorized sensor call

- **WHEN** a chart sensor, including the pie and scatter sensors, receives an
  unknown, cross-session, missing, or changed ID
- **THEN** it returns a structured error without revealing the source path or
  producing an overlay

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

The tool SHALL infer the plot frame and axis directions from visible axes,
ticks, grid or trace evidence rather than treating a fixed crop boundary as
ground truth. It SHALL preserve trace and axis geometry in source-image
coordinates, support small affine rotations of flat two-dimensional charts,
and report fit residuals or confidence for materially uncertain frame and
calibration evidence. A trace crossing, overlap, or color-preserving series
intersection SHALL NOT merge distinct series solely because their pixels are
nearby.

The tool SHALL distinguish marker-derived points from points sampled at
reliable X-axis anchors. It SHALL NOT treat arbitrary pixel-density peaks,
unanchored local extrema, annotations, or a continuous trace as confirmed data
points. When no reliable sampling anchor exists, it SHALL preserve trace
geometry and report the sampling limitation instead of claiming a complete
point count.

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

#### Scenario: Clean axes and legend are correlated

- **WHEN** a sensor processes a clean Cartesian fixture with visible axes and a
  legend
- **THEN** the structured result identifies the common plot area and includes
  the available axis and legend evidence
- **AND** the series identifiers used in geometry and overlays are consistent
  across the returned evidence

### Requirement: Cartesian sensor confidence and warnings

Every successful Cartesian sensor result SHALL include bounded confidence
metadata and a warnings collection. Confidence values SHALL be within `[0, 1]`
and warnings SHALL identify material uncertainty such as merged geometry,
unreadable ticks, unresolved legend mappings, or incomplete calibration. A low
confidence result SHALL remain usable evidence and SHALL not be converted into
an unstructured exception solely because it is uncertain.

#### Scenario: High-confidence fixture reports bounded confidence

- **WHEN** a clean fixture is processed with complete geometry, axes, and legend
  evidence
- **THEN** the result includes confidence values in `[0, 1]`
- **AND** the warnings collection is empty or contains only non-material notes

#### Scenario: Ambiguity becomes an explicit warning

- **WHEN** a sensor cannot reliably resolve a series label or numeric axis
- **THEN** the result includes a material warning naming the unresolved evidence
- **AND** every emitted confidence value remains within `[0, 1]`

### Requirement: Independent pie-sector extraction tool

The system SHALL provide an `extract_pie_slices` tool for ordinary two-
dimensional pie charts. The tool SHALL return a unified source-image evidence
result containing image dimensions, bounded orientation or transform evidence,
a detected plot region, circular geometry, and one structured entry per
reliably detected sector. Each sector SHALL include a stable identifier,
source-image boundary or polygon evidence, color evidence, start and end
angles, angular size, and a normalized ratio only when the geometry evidence
passes the tool's support and residual gates. The tool SHALL preserve partial
geometry and pixel evidence when some sectors, boundaries, or associations
cannot be resolved.

The tool SHALL treat ordinary circular pies as the supported geometry. It MUST
remain bounded for translated, resized, and supported rotated images, and MUST
mark strong perspective, elliptical, three-dimensional, donut, exploded,
nested, or otherwise unsupported geometry instead of fabricating a complete
flat pie measurement.

#### Scenario: Clean pie sectors are measured with source geometry

- **WHEN** `extract_pie_slices` is called with a clean synthetic pie chart whose
  sectors have distinguishable colors
- **THEN** the result contains the true number of reliably detected sectors
  within the declared fixture tolerance
- **AND** each sector contains a stable ID, source-image boundary evidence,
  color evidence, angle evidence, and a ratio matching the ground truth within
  the declared tolerance
- **AND** the result contains detected plot-region, center, radius, and
  source-image size evidence

#### Scenario: Translated, resized, or rotated pies preserve geometry

- **WHEN** the same ordinary pie chart is translated, resized, or rotated
  within the supported image transformation range
- **THEN** the sensor keeps sector identities, angular spans, and ratios
  stable within the declared tolerance
- **AND** all serialized geometry and generated overlay coordinates remain
  aligned with the transformed source image
- **AND** the result records the supported transform or orientation evidence
  rather than treating a fixed crop boundary as the chart geometry

#### Scenario: Narrow, anti-aliased, or separated sectors remain bounded

- **WHEN** sector boundaries contain anti-aliasing, separator gaps, narrow
  sectors, or small color-sampling interruptions
- **THEN** the sensor uses consistent multi-radius or boundary support to
  preserve a sector when evidence is sufficient
- **AND** it reports boundary support, residual, or uncertainty when the
  measured span is incomplete or ambiguous
- **AND** it does not split, merge, or assign a ratio solely from an
  unsupported single-pixel gap or color match

#### Scenario: Cartesian axes are not required

- **WHEN** a pie chart has no x-axis, y-axis, or numeric tick labels
- **THEN** the sensor still measures sector geometry and ratios when circular
  evidence passes its gates
- **AND** it does not report missing Cartesian calibration as a sensor failure

#### Scenario: Unsupported pie geometry remains inspectable

- **WHEN** the input is a strong-perspective, elliptical, three-dimensional,
  donut, exploded, nested, or otherwise unsupported circular graphic
- **THEN** the result preserves any bounded plot-region or partial pixel
  evidence that can be established
- **AND** it marks the geometry as unsupported or low confidence with a
  material warning
- **AND** it does not emit a complete flat-pie sector ratio dataset

#### Scenario: Non-pie image remains inspectable

- **WHEN** the input contains no reliable circular pie region
- **THEN** the tool returns an empty sector list with a bounded warning rather
  than fabricating sectors or raising an exception
- **AND** any generated overlay preserves the source dimensions and explains
  that no reliable pie region was found

#### Scenario: Missing or malformed input is bounded

- **WHEN** `extract_pie_slices` receives a missing, unauthorized, malformed, or
  non-image input
- **THEN** it returns a structured error without exposing a local source path
  or producing a visual artifact

### Requirement: Pie labels and legend associations are explicit

The pie sensor SHALL return detected legend entries, OCR snippets, and
label-to-sector associations as bounded evidence when available. Association
search SHALL support labels and legends around the detected plot region rather
than assuming one fixed side. A resolved association SHALL include its source,
support, or confidence; an unresolved or ambiguous association SHALL remain
null or uncertain and SHALL be reported in warnings instead of being silently
guessed. Printed percentages or numeric values SHALL be retained separately
from geometry-derived ratios.

#### Scenario: Legend labels are associated with sectors

- **WHEN** a clean pie chart has a legend whose colors match the sectors and
  the legend is placed on any supported side or layout
- **THEN** the result associates each reliably matched legend label with the
  corresponding stable sector ID
- **AND** sector color, legend geometry, label source, and association evidence
  remain available for Agent review

#### Scenario: External labels and leader lines retain evidence

- **WHEN** a pie chart places labels outside the circle and connects them to
  sectors with leader lines or spatial ordering
- **THEN** the sensor preserves the label location and the geometric or
  leader-line evidence used for the association
- **AND** it marks the association unresolved or ambiguous when the evidence
  cannot distinguish between sectors

#### Scenario: Printed values are distinguished from inferred ratios

- **WHEN** a pie chart contains percentage or numeric labels
- **THEN** the result records the recognized printed value and its association
  confidence separately from the sector's geometry-derived ratio
- **AND** an unrecognized or conflicting printed value does not overwrite the
  geometry evidence

#### Scenario: Ambiguous association is surfaced

- **WHEN** two sectors or labels have insufficiently distinguishable color,
  spatial, OCR, or leader-line evidence
- **THEN** the affected association is unresolved or marked uncertain
- **AND** the result contains a warning naming the ambiguity

### Requirement: Pie totals, confidence, and visual evidence are validated

Every pie sensor result SHALL include bounded confidence metadata and warnings
for geometry, sector support, association, and total consistency. It SHALL
report angle and ratio totals, per-sector support or residual evidence when
available, and SHALL identify when the reliably detected sectors do not
account for approximately 360 degrees or 100 percent within the configured
tolerance. The sensor SHALL generate a source-sized overlay marking the
detected plot region, center/radius or boundary geometry, sector boundaries,
stable IDs, colors, resolved associations, and unresolved or unsupported
evidence when present.

#### Scenario: Consistent pie totals pass

- **WHEN** detected sectors cover the pie circle and their ratios sum within
  tolerance of 1.0
- **THEN** the result marks the totals as consistent, keeps all confidence
  values within `[0, 1]`, and returns the source-sized overlay
- **AND** the geometry, sector support, and association status are available
  separately from the overall confidence

#### Scenario: Incomplete sectors produce a warning

- **WHEN** sector boundaries are occluded, merged, narrow beyond reliable
  resolution, or otherwise leave an angle or ratio total outside tolerance
- **THEN** the result preserves the detected sectors and reports a bounded
  total-consistency warning
- **AND** it does not present the incomplete result as a certain complete pie

#### Scenario: Overlay uses one source-image coordinate convention

- **WHEN** the pie sensor returns valid or partial geometry
- **THEN** the overlay draws the same center, boundary, sector IDs, and labels
  represented in the serialized result
- **AND** its dimensions match the original source image
- **AND** material residuals, unresolved associations, or unsupported geometry
  are visible without changing the source dimensions

#### Scenario: Generated evidence is model-visible

- **WHEN** the pie sensor returns structured data and a valid overlay
- **THEN** the existing Agent visual-observation path presents the overlay on
  the next model turn while keeping the structured result available
- **AND** richer pie evidence does not require a new Gateway route or a new
  frontend preview protocol

### Requirement: Pie restoration remains freely planned

The system SHALL enable the Agent, given a clean annotated or legend-defined
pie chart through the normal authorized attachment path, to use pie evidence
and assemble a pie ChartSpec without axes through the atomic construction and
validation gate. The infrastructure MUST NOT force a fixed pie-tool sequence
or require ChartSpec output for descriptive image questions.

#### Scenario: Agent restores a clean pie chart

- **WHEN** the user attaches a clean pie chart and asks for its underlying data
- **THEN** the Agent can choose `extract_pie_slices`, visual inspection, OCR,
  and `assemble_spec` in an order it determines
- **AND** the resulting categorical dataset preserves the resolved labels and
  either the recognized numeric values or the explicitly chosen normalized
  ratios

#### Scenario: Pie ChartSpec does not require axes

- **WHEN** the Agent assembles a valid pie result with categorical points and
  no Cartesian axes
- **THEN** `assemble_spec` accepts the result when the dataset and point values
  are valid

#### Scenario: Descriptive pie question does not require restoration

- **WHEN** the user asks a descriptive question about a pie image rather than
  requesting structured data
- **THEN** the Agent can answer without invoking the pie sensor or assembling a
  ChartSpec

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

#### Scenario: Clean single-series scatter points are measured

- **WHEN** `extract_scatter_points` is called with a synthetic single-series
  scatter chart containing distinguishable point markers and readable axes
- **THEN** the result contains the true number of reliably visible points
  within the declared fixture tolerance
- **AND** each point has a stable ID, pixel location, and calibrated x/y values
  matching the fixture ground truth within the declared tolerance
- **AND** the result contains detected plot-area and axis-calibration evidence

#### Scenario: Rotated scatter geometry remains source-aligned

- **WHEN** `extract_scatter_points` is called with a flat scatter chart rotated
  by a small affine angle within the supported range
- **THEN** the result reports `orientation: "oblique"` and retains frame, axis,
  and point positions in source-image coordinates
- **AND** calibrated values are produced only when the rotated axis transforms
  satisfy the declared support, residual, and confidence thresholds
- **AND** ambiguous orientation or excessive residual lowers confidence and
  produces a warning rather than silently dropping points

#### Scenario: Multiple scatter series remain distinct

- **WHEN** a clean scatter chart contains multiple color-distinguished series
  with a legend and overlapping x coordinates
- **THEN** the result contains one series entry per reliably detected series
- **AND** points from different series are not merged solely because their
  coordinates overlap
- **AND** each series carries its legend label when reliably associated, or a
  stable color-based identity with an explicit association warning

#### Scenario: Partial calibration remains inspectable

- **WHEN** point geometry is detected but one or both axes cannot be calibrated
  reliably
- **THEN** the result preserves pixel points, appearance evidence, and any
  partial series association
- **AND** it omits semantic x/y values unless both axes are reliable
- **AND** it reports a warning identifying the missing or insufficient
  calibration

#### Scenario: Non-scatter image remains inspectable

- **WHEN** the input contains no reliable scatter point population
- **THEN** the tool returns an empty series or points collection with a bounded
  warning rather than fabricating points or raising an exception
- **AND** any generated overlay preserves the source dimensions and explains
  that no reliable scatter evidence was found

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
- **AND** it reports the affected count or association as uncertain in warnings
  rather than claiming a precise point count

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
- **THEN** the result retains those points with their normal coordinates and
  marks the potential outlier status as bounded evidence or a warning
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
  and separable markers
- **THEN** the result contains confidence values in `[0, 1]`, calibrated axis
  evidence, and the source-sized overlay
- **AND** the overlay visibly marks the frame, axes, each returned point, and
  its stable identity

#### Scenario: Incomplete scatter evidence produces warnings

- **WHEN** markers are merged, axes are unreadable, or a series association is
  ambiguous
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
ChartSpec with axes through the atomic construction and validation gate. The
infrastructure MUST NOT force a fixed scatter-tool sequence or require
ChartSpec output for descriptive image questions.

#### Scenario: Agent restores a clean scatter chart

- **WHEN** the user attaches a clean scatter chart and asks for its underlying
  data
- **THEN** the Agent can choose `extract_scatter_points`, visual inspection,
  OCR, and `assemble_spec` in an order it determines
- **AND** the resulting dataset preserves resolved series identities and
  calibrated x/y coordinates when reliable
- **AND** uncertain or pixel-only points remain explicitly retained or flagged
  before semantic assembly

#### Scenario: Scatter ChartSpec requires valid Cartesian axes

- **WHEN** the Agent assembles a scatter result with coordinate points but
  missing or invalid Cartesian axes
- **THEN** `assemble_spec` returns located issues without crashing
- **AND** a corrected result with valid x/y axes can pass through the same
  atomic assembly gate

#### Scenario: Descriptive scatter question does not require restoration

- **WHEN** the user asks a descriptive question about a scatter image rather
  than requesting structured data
- **THEN** the Agent can answer without invoking the scatter sensor or
  assembling a ChartSpec

### Requirement: Chart sensors consume bounded dashboard panel scopes

The bar, line, scatter, and pie observation tools SHALL accept a stable panel
handoff from dashboard decomposition and use its bounded local analysis scope
when one is available. The handoff SHALL preserve the source attachment,
source-image origin, local-to-source transform, panel identity, and uncertainty.
The panel scope SHALL constrain the search area but SHALL NOT replace the
chart-specific sensor's independent detection of plot frame, axes, marks,
baseline, center, or calibration.

#### Scenario: Bar sensor uses the selected panel scope

- **WHEN** the Agent invokes the bar sensor with a valid panel identifier
- **THEN** bar geometry detection is limited to the corresponding panel scope
- **AND** each returned bar and baseline remains attributable to the source
  image and panel identity

#### Scenario: All chart types share the same handoff

- **WHEN** a valid panel identifier targets a line, scatter, or pie chart
- **THEN** the corresponding sensor consumes the same panel handoff contract
- **AND** it preserves chart-specific Cartesian or polar evidence without
  depending on another chart detector

#### Scenario: Panel scope is coarser than the plot

- **WHEN** the selected panel includes titles, legends, labels, and a plot
- **THEN** the sensor searches within the panel scope but independently resolves
  its chart-specific measurement frame
- **AND** surrounding annotations are not automatically emitted as marks or
  calibrated geometry

#### Scenario: Panel handoff is missing or invalid

- **WHEN** a panel identifier cannot be resolved for the requested attachment
- **THEN** the sensor returns a bounded routing error or explicitly warned
  source-image fallback
- **AND** it does not claim that an unrelated full-dashboard measurement is a
  panel-local result

#### Scenario: Local results preserve source coordinates

- **WHEN** a sensor measures geometry within a local panel scope
- **THEN** its structured result and visual overlay use the shared source-image
  coordinate convention
- **AND** the local origin and transform remain available for downstream
  evidence fusion

### Requirement: Chart observations consume local panel scope

OCR、柱状图、折线图、饼图和散点图观测工具 SHALL 支持使用 attachment ID 与 panel ID 指定分析范围。指定 panel scope 后，工具 SHALL 在局部裁剪上运行，并在结果中同时提供 panel ID、局部尺寸、源图尺寸和局部坐标到源图坐标的映射。

#### Scenario: OCR excludes unrelated dashboard text

- **WHEN** OCR 被请求分析一个具体 chart panel
- **THEN** 返回文字主要来自该 panel 的局部范围
- **AND** 每个文字框可转换回源图坐标

#### Scenario: Bar measurement is scoped to one panel

- **WHEN** 柱状图传感器收到一个 panel ID
- **THEN** 它不得把相邻 panel 的柱子或标签作为当前图表证据
- **AND** overlay 和结构化结果保留局部及源图坐标信息

### Requirement: Unscoped dashboard analysis remains explicit

当工具没有 panel scope 且输入图像可能包含多个独立面板时，系统 SHALL 将结果标记为 unscoped 或要求先解析面板，不得把整图结果伪装成某个具体面板的确定性证据。

#### Scenario: Full-image observation is marked unscoped

- **WHEN** 模型在多面板图片上未提供 panel ID
- **THEN** 工具结果包含明确的 unscoped 警告
- **AND** 结果不得被自动归因给某一个面板
