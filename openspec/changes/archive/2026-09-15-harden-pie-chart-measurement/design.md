## Context

The existing pie sensor is deliberately independent of Cartesian calibration,
but it currently combines region detection, radial color sampling, sector
segmentation, and semantic association in a compact implementation. Its
candidate circle is inferred from nearby color components, sector labels are
sampled at a small fixed set of radii, and legend matching is biased toward
swatches on the right of the circle. The current overlay and review consumer
also read flat sector fields directly. See `proposal.md` and the modified
`chart-understanding` delta for the required behavior.

The implementation must keep using source-image coordinates, bounded
`ToolResult` evidence, the authorized attachment boundary, and the Conda
`agent` environment with the existing Pillow/NumPy/OCR dependencies. The
change must not introduce a Cartesian-axis requirement or alter the existing
pie ChartSpec serialization.

## Goals / Non-Goals

**Goals:**

- Make ordinary two-dimensional pie measurement evidence-driven and inspectable
  in the same style as the hardened bar, line, and scatter sensors.
- Separate plot-region geometry, sector measurement, semantic association,
  confidence, and warnings so partial evidence can be reviewed safely.
- Support translated, resized, and supported rotated source images without
  deriving geometry from fixed crop edges or fixed legend placement.
- Gate semantic ratios on sector support and residual quality while retaining
  useful pixel and angular evidence for incomplete cases.
- Migrate the overlay, generated-chart review, fixtures, tests, and docs as one
  intentional result-contract change.

**Non-Goals:**

- Adding a new `ChartType`, Gateway route, frontend preview protocol, or
  persistence format.
- Implementing donut, exploded, nested, photorealistic, or fully perspective/
  3D pie understanding; these remain explicitly bounded unsupported cases.
- Reconstructing exact source numeric values from geometry when the image only
  supports a normalized ratio.
- Requiring OCR to make sector geometry usable.

## Decisions

### 1. Keep a pie-specific geometry pipeline and adopt the shared evidence style

Pie charts do not have Cartesian axes, so the sensor will remain separate from
the Cartesian frame and axis-fit helpers. It will nevertheless follow the
same contract principles as the hardened sensors: source-image dimensions,
orientation/transform evidence, explicit geometry, optional calibrated
semantics, confidence components, warnings, and bounded errors.

Alternative: force pie data through the shared Cartesian frame abstraction.
Rejected because a missing x/y axis is valid pie evidence and would create a
false calibration failure.

### 2. Infer and score a plot-region hypothesis before sampling sectors

The sensor will collect bounded color/edge/component candidates and score them
as possible pie regions using circularity, shared center evidence, radial
coverage, area, and separation from legend-like components. It will retain the
best candidate only when its support clears the configured threshold; otherwise
it will return an inspectable empty or partial result.

The fitted region will serialize center, outer radius, source bbox or polygon,
fit residual, and confidence. A normal pie is represented as a circle in the
supported image plane. Elliptical, strongly perspective, 3D, donut, or nested
regions are classified as unsupported rather than silently flattened into a
circle.

Alternative: use the bounding box of the largest nearby color components as the
circle. Rejected because legend swatches, annotations, partial sectors, and
anti-aliased edges can move that envelope without representing the plot region.

### 3. Use multi-radius sector evidence with explicit quality gates

Sector candidates will be derived from angular color evidence sampled across
the fitted region, not from one fixed radius. The implementation will combine
consistent runs across interior radii, the outer boundary, separator evidence,
and local color support. Each candidate retains angular span, boundary
positions, color identity, support, and residual/uncertainty metadata.

The angular ratio is computed from the accepted span and is eligible for the
semantic `measure` field only when coverage, run stability, and total-quality
thresholds pass. If a boundary is merged, occluded, too narrow, or color-
ambiguous, the sensor keeps the partial geometry where possible and marks the
ratio or sector association uncertain instead of inventing a split.

Alternative: keep the current fixed radii and only tune tolerances. Rejected
because tolerance changes cannot distinguish a real narrow sector from a
separator gap or a legend/label color match.

### 4. Define deterministic source-image geometry and sector identity

All detection, serialization, and drawing use one source-image coordinate
convention. Angles use one documented clockwise convention and are normalized
to `[0, 360)`. Sector IDs are assigned deterministically from the accepted
clockwise ordering and are independent of OCR success. The result records
supported image rotation or transform evidence without treating rotation as a
new chart semantic.

Alternative: use array-index order and overlay-specific coordinate conversion.
Rejected because scan-origin changes and separate drawing math can reorder
sectors or recreate the baseline/overlay misalignment seen in earlier tools.

### 5. Make association a separate evidence stage

Legend and OCR processing will run after sector geometry exists. Candidate
labels are searched in bounded regions around the plot, and associations use
color, angular position, spatial proximity, and leader-line evidence when
available. The result keeps raw OCR snippets, legend geometry, association
source, support, and confidence separate from the geometry-derived ratio.

Alternative: use OCR text or legend order to determine sector boundaries.
Rejected because semantic labels must not create or repair missing geometry;
the Agent can inspect unresolved associations after the sensor returns.

### 6. Use confidence as an evidence gate, not a cosmetic score

Confidence will be decomposed into plot-region fit, sector support, association,
and total consistency. The overall score is bounded, but a high association
score cannot compensate for a failed geometry gate. Review and ChartSpec
restoration will consume only accepted ratios or explicitly preserve partial
evidence and warnings.

Alternative: always return a best-effort ratio with a lower overall confidence.
Rejected because downstream review could mistake a numerically plausible ratio
for a measured source value.

### 7. Render overlays directly from the unified result

`render_pie_overlay` will consume only the new serialized geometry contract.
It will draw the fitted region, center/radius, boundaries, IDs, ratios,
associations, and uncertainty in source-image pixels. Empty and unsupported
results will still produce a source-sized explanatory overlay when image input
was valid.

Alternative: keep a second overlay-specific representation. Rejected because
it would permit detection, serialized evidence, and visual review to disagree.

### 8. Migrate consumers explicitly and preserve transport compatibility

The pie branch in generated-chart review will compare expected and detected
ratios only from accepted measurement fields, and will turn incomplete or
unsupported evidence into bounded review warnings rather than hard failures
where appropriate. Tests, fixtures, Agent trajectories, frontend mock payloads,
and OpenSpec documentation will be migrated in the same change. The existing
visual-observation, artifact, preview, and authorized attachment transport
remain unchanged.

## Risks / Trade-offs

- **Similar sector colors can merge or fragment.** Use multi-radius support,
  boundary residuals, deterministic color identities, and explicit unresolved
  warnings; never infer hidden splits from expected dataset count.
- **Legend swatches and annotations can look like sectors.** Score candidates
  by circular plot coherence and scope association searches to the fitted
  region and its bounded neighborhood.
- **Anti-aliasing and separator gaps shift angular boundaries.** Normalize one
  angular convention, aggregate across radii, and assert fixture tolerances
  rather than relying on single-pixel edges.
- **OCR or external labels may be incomplete.** Keep geometry independent,
  preserve raw snippets, and return unresolved associations for Agent review.
- **A rotated image may preserve circular geometry while text becomes hard to
  read.** Keep geometry usable when its fit is strong, but lower association
  confidence and retain OCR warnings independently.
- **A circular logo or photograph may be a false positive.** Require coherent
  radial sectors and total support, and return low-confidence partial evidence
  when the pie hypothesis is not strong enough.
- **The result contract is intentionally breaking for pie consumers.** Search
  the repository for all legacy pie fields, update review/tests/mocks together,
  and add clean plus partial regression fixtures before removing compatibility
  assumptions.

## Migration Plan

1. Define and test the new pie evidence model and coordinate helpers while
   keeping the existing ChartSpec `pie` shape unchanged.
2. Replace pie-region/sector extraction, then update the overlay and pie review
   comparison to the unified fields.
3. Migrate fixtures, unit tests, attachment-boundary tests, Agent-loop tests,
   frontend mock observations, and documentation; search for stale fields.
4. Run focused pie tests, the full `conda run -n agent` suite, frontend build
   and smoke checks, `git diff --check`, and strict OpenSpec validation.

Rollback consists of reverting the pie sensor, overlay, consumer, and test
migration as one change. No database or persisted observation migration is
required because observations are bounded per-run evidence.

## Open Questions

None that change the specified scope or approach. Exact support/residual
thresholds can be selected against deterministic fixtures during
implementation, provided they are encoded in tests and preserve partial
evidence rather than weakening the evidence gates.
