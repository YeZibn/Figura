## Context

See `proposal.md` for the motivation and behavior scope. The current line
sensor shares a fixed `default_plot_area` with other Cartesian sensors, finds
candidate x positions from per-column color density, and derives each point's
y position from a small vertical pixel strip. It returns useful evidence for
clean generated charts, but it has no explicit distinction between a
continuous trace and a confirmed sample point, no source-image frame model for
rotation, and no calibration residual that can downgrade an uncertain result.

The previous bar change deliberately used a bar-specific frame and migrated
its consumers as one breaking result-contract change. This design applies the
same pattern to line charts without silently changing scatter behavior.

## Goals / Non-Goals

**Goals:**

- Establish a source-image geometry contract for line-chart frames, axes,
  traces, markers, and sampled points.
- Infer the chart frame from image evidence instead of relying on a fixed
  proportional crop.
- Separate continuous trace detection from semantic point sampling.
- Support clean upright and small-affine-rotated two-dimensional numeric line
  charts, including multiple series, crossings, overlaps, and signed values.
- Preserve partial pixel evidence and make calibration, sampling, and series
  uncertainty explicit in warnings and confidence metadata.
- Migrate overlays, tests, end-to-end observations, and mock payloads to one
  result contract.

**Non-Goals:**

- Generalizing the shared Cartesian frame for scatter and pie sensors in this
  change; shared helper changes are allowed only when they are behaviorally
  neutral for existing consumers.
- Supporting strong perspective, 3D, filled-area, dual-axis, logarithmic, or
  heavily occluded charts as reliable semantic data.
- Inferring arbitrary data samples from an unanchored continuous curve.
- Extending ChartSpec to add categorical or non-numeric x coordinates; those
  inputs remain bounded pixel/label evidence in this change.
- Introducing a computer-vision or numerical runtime dependency.

## Decisions

### 1. Use a line-specific frame rather than changing `default_plot_area`

The sensor will infer a line-chart frame from visible axes, tick positions,
grid evidence, trace extent, and image boundaries. The serialized frame will
retain source-image geometry and may represent a small affine rotation through
axis endpoints or a frame polygon.

This follows the bar change's decision to keep orientation-specific geometry
out of a shared crop helper. Changing `default_plot_area` for every Cartesian
sensor would expand the migration surface and could alter scatter behavior
without line-specific tests proving the change is safe.

Alternative considered: adjust the fixed crop ratios and add tolerances.
Rejected because a crop ratio cannot represent rotated axes, cropped frames,
or a plot whose visible bounds differ from the renderer's margins.

### 2. Keep trace geometry separate from confirmed points

Each series will expose ordered source-image trace geometry, while points will
carry a source classification such as marker-derived or x-anchor sampled.
Only marker centers or reliable x-axis anchors can create confirmed points.
Continuous line density and local extrema are evidence for the trace, not
proof of a sample.

Alternative considered: retain the existing per-column peak detector and tune
its threshold for more fixtures. Rejected because the threshold cannot know
whether a peak is a marker, a steep segment, a dense sample, or a legend
artifact.

### 3. Calibrate through an explicit two-axis transform

The sensor will fit numeric mappings for the x and y axes from paired pixel
positions and OCR/tick values. For a small rotation, pixel positions are
projected into the fitted axis directions before applying the mappings. Fit
residuals and the number/quality of supporting ticks determine whether
semantic x/y values are emitted.

If only one axis is calibrated, the result keeps pixel trace and point
positions but does not emit partially fabricated semantic coordinates. The
zero value is used only when supported by axis/tick evidence; image height
alone does not establish a signed y value.

### 4. Preserve series identity independently from geometric proximity

Color masks will be constrained to the inferred frame before trace extraction.
Legend evidence will be associated separately, and each series will retain a
stable fallback identity when its label is unresolved. Crossing or overlapping
traces remain separate when color evidence supports that distinction; merged
or occluded sections lower confidence and produce warnings.

Alternative considered: assign points by nearest geometric path after all
colors are merged. Rejected because crossings would swap identities and
overlaps would make the association look more certain than the image allows.

### 5. Treat markerless sampling as an anchored operation

For markerless charts, the sensor may sample at reliable ordered x-axis ticks
or equivalent anchors. It will not create points at arbitrary local density
peaks. If no anchors are reliable, it returns the continuous trace and a
sampling warning; a later agent action can use OCR or visual evidence before
assembling a ChartSpec.

This preserves the distinction between what the image proves and what a model
might reasonably hypothesize from a smooth curve.

### 6. Keep source-image coordinates and overlay conversion aligned

Serialized axis endpoints, frame polygons, trace vertices, and point positions
will use source-image pixel coordinates with one explicit edge convention.
The overlay will draw those same coordinates, converting only at the drawing
boundary when the raster API requires inclusive endpoints. It will draw the
measured trace rather than reconstructing a new line solely from returned
points, and will mark point source, IDs, calibration status, and uncertainty.

### 7. Migrate the result contract as one intentional change

The line result will evolve from a point-only observation to a trace-and-point
observation. Known in-repository consumers, tests, fixtures, end-to-end
trajectories, and frontend mock traces will migrate together. No adapter will
emit both an obsolete point interpretation and the new evidence contract.

## Risks / Trade-offs

- **Axis lines are faint, cropped, or absent** → retain trace/marker pixels,
  omit unsupported semantic values, and lower calibration confidence.
- **Legend swatches or annotations match a series color** → restrict trace
  candidates to the inferred frame and report residual contamination as a
  warning rather than silently adding points.
- **Anti-aliasing fragments a colored trace** → preserve ordered fragments,
  bridge only bounded gaps supported by continuity, and mark unresolved gaps.
- **Multiple traces cross or overlap** → keep color-separated evidence,
  expose overlap/occlusion warnings, and avoid claiming a complete point
  count where identity cannot be established.
- **Rotation causes axis and tick positions to drift** → fit source-image
  axis directions and require residual/confidence thresholds before emitting
  calibrated values.
- **Markerless curves do not reveal their original sampling density** → only
  sample at reliable x anchors and keep unanchored geometry separate from
  semantic points.
- **Categorical x labels cannot be represented by the current line ChartSpec**
  → preserve labels and pixel evidence, report the bounded limitation, and
  do not silently convert labels into numeric values.
- **Changing overlays changes model-visible evidence** → add pixel-size and
  identity assertions for every supported fixture before migrating consumers.

## Migration Plan

1. Add the line-specific frame, axis-transform, trace, and point evidence
   contract while keeping the direct callable boundary structured.
2. Replace fixed-frame/peak-only extraction with evidence-backed trace
   extraction, marker detection, anchored sampling, calibration residuals, and
   bounded warnings.
3. Update line overlay rendering to consume the new source-image geometry and
   display traces, points, axes, identities, and uncertainty.
4. Migrate tests, fixtures, end-to-end trajectories, frontend mock payloads,
   and any chart-review consumers that read the old line observation shape.
5. Search the repository for stale point-only assumptions and validate the
   active OpenSpec change before implementation handoff.

Rollback is a source-level revert before archive. The observation data is
per-run evidence, so no persisted-data migration is required.
