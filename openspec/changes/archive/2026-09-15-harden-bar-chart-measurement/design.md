## Context

See `proposal.md` for the motivation and scope. The current bar sensor uses a
fixed Matplotlib-like plot rectangle from `default_plot_area`, scans only image
columns, derives a scalar `baseline_y` from candidate bottoms, and draws
inclusive PIL rectangles with coordinates that do not share an explicit edge
convention. The current result also duplicates or hard-codes vertical-only
fields. Review logic currently compares `h_px`, while tests and mock traces
assert the legacy result shape.

## Goals / Non-Goals

**Goals:**

- Establish one bar-result schema for vertical, horizontal, rotated, positive,
  negative, grouped, and stacked two-dimensional bars.
- Detect the actual zero baseline or shared bar edge instead of using the crop
  boundary as ground truth.
- Preserve polygon evidence and signed value-axis measurements.
- Make overlay geometry use the same coordinate convention as detection.
- Migrate all known in-repository consumers to the new contract in the same
  change.

**Non-Goals:**

- Generalizing the geometry foundation for line, scatter, or pie sensors.
- Full projective rectification of photographs.
- Reliable extraction from 3D, perspective-rendered, heavily occluded, or
  ambiguous bar charts; these cases receive bounded warnings.
- Reading semantic numeric values from axes; this change measures image
  geometry and relative lengths only.

## Decisions

### 1. Use a bar-specific frame rather than changing shared Cartesian helpers

The change is intentionally limited to bar charts. A bar-specific frame keeps
the current line, scatter, and pie sensors stable while allowing bar detection
to reason about orientation, zero axis, and bar polygons. The frame records the
source-image plot bbox/polygon and the detected value/category directions.

Alternative considered: change `default_plot_area` and shared evidence fields
for every Cartesian sensor in this change. Rejected because it expands the
change surface and would mix unrelated sensor migrations.

### 2. Infer the baseline from geometry, not from a fixed crop edge

Candidate extraction will retain full evidence long enough to find common bar
edges, visible axis lines, or a reliable zero-axis cluster. A fitted baseline
is serialized as two source-image endpoints with residual and confidence. A
candidate is not removed merely because its bottom differs from a horizontal
scalar by a few pixels.

Alternative considered: keep a scalar baseline and increase the alignment
tolerance. Rejected because it still cannot represent rotation, horizontal
bars, negative values, or a crop boundary that truncates the bars.

### 3. Normalize all measurements along the value axis

Every bar stores `geometry.bbox_px`, `geometry.polygon_px`, and
`measure.value_length_px`. The value length is signed relative to the zero
baseline; `measure.ratio` uses absolute lengths. This makes vertical and
horizontal bars use the same consumer contract and prevents `h_px` from being
misread as a semantic bar value.

### 4. Use explicit mode and association fields

The top-level `orientation` and `bar_mode` describe the chart. Each bar uses
`series_id`, `category_index`, and optional `stack` data. Top-level `series`
is the single source for series colors and optional labels; a duplicate
`legend` envelope is not emitted by the bar sensor.

Alternative considered: keep both `legend` and `series` for compatibility.
Rejected because the current bar sensor populates them with the same data and
the duplication makes unresolved associations look more authoritative.

### 5. Treat the result schema change as an intentional breaking migration

The user has authorized removal of unused legacy fields. The implementation,
review manager, tests, fixtures, mock trace, and OpenSpec contract will migrate
together. No compatibility adapter will emit both old and new fields.

### 6. Keep visual evidence in original image coordinates

Any intermediate orientation reasoning may use normalized or rotated
coordinates, but serialized polygons, baseline endpoints, and overlay drawing
will use source-image pixels. This keeps the generated evidence directly
inspectable and avoids a second transform contract in the frontend.

## Risks / Trade-offs

- **Color masks include legends or annotations** → constrain candidates by bar
  shape, plot-frame membership, connected regions, and category alignment;
  retain warnings when evidence remains ambiguous.
- **Anti-aliasing shifts visible edges by one pixel** → define one half-open
  internal bbox convention, convert to inclusive drawing endpoints only at the
  overlay boundary, and test source/overlay alignment at pixel level.
- **Rotated bars have different bottom y values** → fit a line in source
  coordinates and measure lengths along the value direction instead of
  filtering by a scalar y value.
- **Negative and stacked bars complicate baseline selection** → identify the
  zero axis before measuring signed lengths; report unknown sign or stack
  geometry when the axis cannot be established.
- **Existing review checks use `h_px`** → migrate review comparisons to
  `measure.value_length_px` before removing the legacy field.
- **Perspective and 3D imagery can resemble flat bars** → classify confidence
  conservatively and return explicit warnings rather than forcing a flat model.

## Migration Plan

1. Add the new bar result contract and internal geometry helpers.
2. Update candidate extraction, baseline inference, orientation handling, and
   overlay drawing.
3. Migrate `review/manager.py`, unit tests, fixtures, end-to-end trajectories,
   and frontend mock trace payloads.
4. Remove all repository references to the legacy bar fields.
5. Run the bar-focused tests, the full Python suite, frontend build/smoke, and
   strict OpenSpec validation.

Rollback is a source-level revert of this change before archive; no persisted
database or attachment migration is required because the changed data is a
per-run tool observation.

