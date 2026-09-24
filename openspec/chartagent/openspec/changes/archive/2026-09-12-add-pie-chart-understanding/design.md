## Context

The existing chart sensors measure Cartesian geometry through plot areas,
axes, ticks, and series colors. `ChartSpec` already models `pie` as a
categorical chart type whose axes may be absent, and the Agent already supports
authorized attachment tools plus model-visible generated images. See
`proposal.md` and the chart-understanding delta for the motivation and
behavioral contract.

## Goals / Non-Goals

**Goals:**

- Add a standalone pie sensor that produces useful sector evidence even when
  no coordinate axes exist.
- Keep geometry, OCR values, and legend associations separate so uncertainty
  is visible to the Agent.
- Reuse the existing `ToolResult`, generated-image, authorized-attachment,
  Agent loop, ChartSpec assembly, and validation boundaries.
- Make failure and partial evidence inspectable through warnings, confidence,
  and source-sized overlays.

**Non-Goals:**

- Donut charts, exploded 3D pies, gauges, treemaps, or arbitrary photographic
  circular objects in the first implementation.
- Reconstructing exact numeric values when an image only supports a geometric
  ratio.
- Adding a new Gateway route, changing the frontend protocol, implementing
  scatter extraction, or rendering ChartSpec back into an image.

## Decisions

### 1. Add a dedicated `extract_pie_slices` sensor

Pie charts use angular geometry rather than Cartesian coordinates, so the tool
will own circular-region detection, center/radius estimation, radial color
sampling, sector boundary detection, and ratio calculation. It will expose a
direct path-compatible Python function and an attachment-authorized Agent
wrapper, matching the existing chart-tool registration pattern.

Alternative considered: extend `measure_bars` or create a generic Cartesian
sensor. Rejected because that would make axis assumptions implicit and would
blur the evidence contract for charts without axes.

### 2. Measure geometry before semantic association

The sensor will first identify a reliable circular region and sample colors
near the sector perimeter while accounting for anti-aliased edges and narrow
separator gaps. Consecutive angular runs become candidate sectors; stable IDs
are assigned in clockwise order from a deterministic reference angle. Labels,
legend entries, and printed values are attached in a later evidence stage and
never used to invent missing geometry.

Alternative considered: ask the VLM to return all sector values directly.
Rejected because the existing architecture intentionally uses deterministic
measurement for geometry and the VLM for semantic association and recovery.

### 3. Keep printed values and inferred ratios distinct

Each sector will expose geometry-derived `angle_deg` and normalized `ratio`.
OCR may additionally provide a printed numeric value, its text, and an
association confidence. The sensor will not silently treat a ratio as a
printed value. When the Agent later calls `assemble_spec`, it can use printed
values when reliable or explicitly choose normalized ratios when only geometry
is available; `validate_spec` remains an independent critic.

Alternative considered: always convert ratios into percentages in the sensor.
Rejected because that hides whether a displayed number came from the source
image or was inferred from pixels.

### 4. Use a common bounded evidence envelope

The result will contain image dimensions, a circular-region record, sector
entries, legend/OCR evidence, totals, confidence, and warnings. The overlay
will be generated only after image validation and will preserve source
dimensions. It will be passed through the existing visual-observation path, so
no new Gateway event type is needed.

Confidence will be decomposed into geometry, label association, and total
consistency components, with an overall bounded value. Total checks will
compare both the sum of angular spans against 360 degrees and the sum of
ratios against 1.0, while allowing a small configured tolerance for raster
sampling and separator pixels.

### 5. Keep the Agent workflow optional

The pie sensor will be registered alongside existing tools. The Agent may call
it, inspect its overlay, load the source image, use OCR or another tool, or
answer directly. No orchestrator-level pie pipeline will be introduced.

## Risks / Trade-offs

- **[Circular-region false positives]** A circular logo or photograph can be
  mistaken for a pie chart -> limit the first scope to clean fixtures, require
  coherent radial color runs, and return low confidence/warnings for weak
  candidates.
- **[Anti-aliasing and separators distort angles]** Pixel runs can over- or
  under-estimate narrow sectors -> sample multiple radii, ignore short
  separator gaps, and validate total coverage before claiming completeness.
- **[Similar colors merge sectors]** Adjacent sectors may be indistinguishable
  -> preserve merged geometry as one uncertain candidate and report the
  association/segmentation warning instead of fabricating a split.
- **[OCR association is noisy]** Labels can be outside the chart or overlap ->
  keep OCR evidence separate, use bounded proximity/color matching, and let
  the Agent re-examine unresolved cases.
- **[Ratio is mistaken for source value]** A normalized ratio may be reported
  as an original numeric value -> carry separate fields and require the Agent
  to choose the value source during assembly.
- **[New algorithm destabilizes existing sensors]** Shared image helpers can
  affect Cartesian behavior -> isolate pie-specific logic and retain the full
  existing Python and OpenSpec verification suites.

## Migration Plan

No data migration is required. Add the sensor and fixtures, register it in the
existing chart registry, and validate it through the current Agent/Gateway
observation path. Rollback consists of removing the pie tool registration and
pie-specific modules; existing ChartSpec and Cartesian consumers remain
unchanged.

## Open Questions

None that change the specified behavior or implementation approach. The exact
fixture tolerances can be selected while implementing against the rasterized
test images, provided the result remains bounded and the tolerance is asserted
by tests.
