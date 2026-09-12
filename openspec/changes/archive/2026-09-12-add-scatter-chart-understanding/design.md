## Context

See `proposal.md` for the motivation and scope. The existing chart-understanding
package already has shared Cartesian layout, palette, OCR tick calibration,
tool registration, attachment authorization, and source-sized overlay patterns.
`ChartSpec` already treats `scatter` as a coordinate-based Cartesian type, so
this change should add image evidence and Agent integration without changing
the IR serialization contract.

## Goals / Non-Goals

**Goals:**

- Add a deterministic sensor for clean two-dimensional scatter plots.
- Reuse the existing plot-area, color palette, OCR tick fitting, confidence,
  warning, attachment, and visual-observation contracts.
- Keep point geometry available even when semantic calibration or legend
  association is incomplete.
- Preserve evidence about marker size, opacity, overlap, and potential outliers
  without treating those observations as unverified data values.
- Support an offline Agent-loop path from authorized attachment to scatter
  evidence, ChartSpec assembly, and independent validation.

**Non-Goals:**

- Bubble-chart semantics where marker area is a required third numeric value.
- 3D scatter plots, heatmaps, density plots, regression-line fitting, or image
  generation.
- A universal chart classifier or a mandatory scatter tool sequence.
- New Gateway routes, frontend-specific result panels, or Tauri/Rust work.
- Storing image bytes, overlay bytes, or large pixel evidence inside ChartSpec.

## Decisions

### 1. Add an independent scatter sensor

Add `extract_scatter_points` next to the existing bar, line, pie, and OCR
tools. It will return a shared Cartesian evidence envelope plus scatter-specific
`series` and `points` data. The sensor remains path-compatible for direct
Python callers, while Agent registration wraps it with the existing authorized
`attachment_id` boundary.

An independent sensor is preferred over extending `extract_line_series` because
line connectivity is not evidence in a scatter plot. Reusing the line sensor
would risk interpreting connecting strokes or dense marker regions as a series
path and would make overlap behavior ambiguous.

### 2. Detect markers from color masks and connected components

For each detected chart color, restrict the mask to the inferred plot area and
extract connected marker components. Record each component's centroid, bounding
box, area, and a bounded opacity/shape-quality measure when available. Filter
obvious gridlines and tiny antialiasing fragments using the existing color
tolerance and minimum geometry conventions, but preserve components that are
large or isolated enough to be potential outliers.

Stable series identities will be color-based (`series_1`, `series_2`, ...), with
legend labels attached when OCR and spatial proximity resolve them. Point IDs
are stable within a series and ordered by calibrated x when calibration is
available, otherwise by pixel x/y. The implementation must not merge points
from different colors merely because their centers overlap.

### 3. Reuse OCR tick calibration, with partial results

Use the existing numeric OCR evidence and linear tick fitting for x and y.
When both fits are available, attach semantic `x` and `y` values to each point.
When either fit is unavailable, retain `x_px` and `y_px`, include the available
axis evidence, and emit a warning instead of extrapolating missing values.

The sensor will use the same coordinate convention as the line sensor, including
the inverted pixel-y relationship represented by the fitted y-axis function.
This keeps scatter points directly compatible with the existing coordinate
`DataPoint` and `assemble_spec` contracts.

### 4. Represent overlap and outlier state as bounded evidence

Components that touch or form a marker-sized cluster will receive a bounded
`overlap`/`merged` evidence record rather than an invented count. Where marker
size or opacity can be measured consistently, retain it as sensor evidence;
do not add a semantic third value to `DataPoint`.

Potential outliers will be identified conservatively from robust spatial
distance within a series, and will remain in the returned point collection with
an `outlier_candidate` marker or warning. This is review evidence, not an
automatic exclusion rule; the Agent decides whether the point belongs in the
assembled dataset.

### 5. Keep visual evidence in the existing observation path

Add a scatter overlay renderer that preserves source dimensions and draws the
plot area, point IDs, series colors, calibration status, and unresolved/merged
or outlier evidence. Return it through `ToolResult` so the existing Agent
visual-observation projection presents it on the next model turn. No Gateway
event or frontend protocol change is needed.

### 6. Validate through existing ChartSpec tools

The scatter sensor will emit evidence suitable for coordinate points with
`series` identities. The Agent may call `assemble_spec` with `chart_type=
"scatter"` and both axis labels, then call `validate_spec` independently.
The sensor does not assemble or validate automatically, preserving the existing
ReAct separation between measurement, semantic choice, and critique.

## Risks / Trade-offs

- [Risk] Anti-aliased markers can produce several connected components or make
  one marker appear larger than it is. -> Use color tolerance, component
  geometry thresholds, and warnings; retain pixel evidence for review.
- [Risk] Overlapping markers cannot always be separated from a static image.
  -> Return a merged/uncertain evidence record and lower confidence instead of
  fabricating a point count.
- [Risk] OCR tick detection may confuse labels, legend text, or sparse ticks.
  -> Require at least two distinct pixel/value pairs for a fit and preserve
  uncalibrated pixel coordinates when that condition is not met.
- [Risk] Color clustering may mistake gridlines or legend swatches for points.
  -> Limit detection to the plot area, reject line-like components, and test
  with non-scatter and gridline-heavy fixtures.
- [Risk] Synthetic fixtures may overstate real-world accuracy. -> Keep scope to
  clean charts, expose confidence and warnings, and include malformed,
  partially calibrated, overlapping, and outlier fixtures.

## Migration Plan

Register the new tool behind the existing chart registry and attachment wrapper;
existing tools and schemas remain unchanged except for the additive scatter
entry. Add tests before enabling any frontend display. Rollback is limited to
removing the scatter registration, sensor, overlay, fixtures, and tests; the
existing ChartSpec scatter type and Cartesian consumers remain valid.
