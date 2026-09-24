## Context

The current scatter sensor can recover marker-like connected components from a
clean image, but it treats a proportional rectangle as the plot area and
accepts weak tick fits without retaining enough evidence to judge them. In a
real RapidOCR run this can leave useful pixel points while losing y-axis
calibration and legend labels. The sensor also imports private helpers from
the line sensor, which makes later changes to either chart type risky.

The bar and line measurement work already establishes the project direction:
coordinates belong to the source image, uncertain calibration must remain
visible, overlays are part of model-visible evidence, and review code should
consume structured evidence instead of guessing from a preview. Scatter needs
the same contract while retaining its distinct marker, series, overlap, and
outlier semantics.

## Goals / Non-Goals

### Goals

- Infer a scatter-specific frame and axis directions from image evidence, with
  source-image geometry preserved for upright and small oblique charts.
- Separate marker/component evidence from semantic coordinates and gate
  calibrated x/y values on axis support, residual, and confidence.
- Preserve stable series identity, legend association evidence, appearance,
  overlap, dense-region, occlusion, and outlier signals without fabricating
  hidden points or values.
- Produce a source-sized overlay that makes frame, axes, points, identities,
  calibration status, and uncertainty inspectable by the Agent and reviewer.
- Remove scatter's dependency on private line-only helpers without changing
  the established bar and line behavior.
- Migrate review, tests, fixtures, end-to-end flows, frontend mock data, and
  documentation to the explicit result contract.
- Keep errors structured and bounded so local image paths do not leak into
  tool results or Agent-visible text.

### Non-Goals

- Changing bar or line extraction behavior as part of this change, except for
  extracting neutral shared numerical helpers with compatibility preserved.
- Supporting arbitrary perspective correction, 3D charts, photographed pages,
  or exact recovery of fully occluded or indistinguishable markers.
- Inferring semantic values when one or both axes lack reliable calibration.
- Turning marker size, opacity, density, or visual outlier status into
  unverified numeric dataset fields.
- Adding a new runtime computer-vision or OCR dependency; OCR continues to
  run through the repository's Conda `agent` environment and RapidOCR path.

## Decisions

### 1. Use a scatter-specific source-image frame

The scatter sensor will own frame detection rather than treating
`default_plot_area` as ground truth. It will combine visible axis lines, tick
marks, gridlines, marker extents, and image boundaries, then retain the
resulting frame and confidence as evidence. The proportional rectangle may be
used as an initial search hint, but it cannot override stronger image
evidence. This avoids changing the global Cartesian behavior used by bar and
line sensors.

Frame, axis endpoints, and marker geometry will be represented in source
pixels. For a small affine rotation, the implementation will estimate axis
directions and project observations onto those directions before applying
numeric transforms. Excessive skew or perspective will be reported as
unsupported or uncertain rather than normalized silently.

### 2. Extract neutral fit helpers and keep compatibility boundaries

Numerical tick parsing, robust line fitting, and fit-quality calculations will
move to a neutral Cartesian helper boundary that can be used by line and
scatter. Existing line-facing behavior and field names will remain compatible
while scatter stops importing private line symbols. Fit results will carry
support, residual, and confidence so callers can apply the same evidence gate
without reimplementing quality checks.

### 3. Treat calibration as an evidence gate, not a best-effort guess

Each axis transform will record its source direction, usable tick count,
numeric range, residual, support span, and confidence. A point receives
semantic x/y only when both transforms satisfy the declared thresholds. If
either axis fails, the point retains source pixel coordinates and the result
records a bounded calibration warning. This intentionally prefers an
inspectable partial result over plausible-looking fabricated coordinates.

### 4. Associate series in the frame, with stable color fallback

Marker candidates will be detected and clustered within or near the inferred
frame, while legend candidates will be searched outside the frame and linked
using normalized color plus spatial association. Anti-aliased colors will use
the existing palette normalization approach where possible. When a legend
label cannot be proven, the sensor will keep a deterministic color-based
series identity and an explicit unresolved-association warning; it will not
silently drop the series or invent a label.

### 5. Preserve marker evidence independently from point semantics

The point model will retain stable ID, source pixel center, component bounds,
appearance, series identity, calibrated values when available, and evidence
flags such as merged, oversized, dense, occluded, or potential outlier. A
merged component remains one uncertain visible observation; hidden marker
counts are not inferred. Outlier candidates remain in the result so the Agent
can make the inclusion decision during ChartSpec assembly.

### 6. Make overlays source-sized and status-bearing

The overlay will be rendered at the original image dimensions and use the same
source-pixel coordinates as the structured result. It will show the inferred
frame, axis directions, tick/calibration status, point IDs, series colors, and
uncertainty markers. Existing preview and observation transport stays
unchanged; only the scatter payload and overlay content become richer.

### 7. Migrate consumers explicitly

Review and end-to-end code will consume the unified scatter result while
preserving pixel-only observations for follow-up visual inspection. Frontend
mock observations and types will be updated only where they describe the
scatter payload; transport and preview contracts will not be redesigned.
Tests will cover clean, rotated, partial-calibration, multi-series, overlap,
dense, outlier, non-scatter, malformed, and path-redaction cases.

## Risks / Trade-offs

- **Incomplete OCR may reduce semantic output.** Mitigation: retain all
  reliable pixel and component evidence, expose per-axis quality, and let the
  Agent request visual/OCR follow-up.
- **Anti-aliasing can fragment one marker or pollute the palette.** Mitigation:
  normalize colors, use connected-component and proximity evidence together,
  and mark ambiguous clusters instead of forcing a split.
- **Legend content can be mistaken for data markers.** Mitigation: scope
  marker detection to the inferred frame and require spatial/color evidence for
  legend association.
- **Overlapping markers cannot always be counted.** Mitigation: preserve the
  merged visible component, bounded appearance, and uncertainty; never claim a
  complete hidden count.
- **Rotation can make axis and tick projections unstable.** Mitigation: use
  source-image axis directions, residual gates, and an explicit oblique or
  unknown orientation with pixel-only fallback.
- **Extracting helpers can regress the line sensor.** Mitigation: add neutral
  helpers behind compatibility wrappers and run the existing line and bar
  regression suite before accepting scatter changes.
- **A richer result is a breaking point payload.** Mitigation: update all
  in-repository consumers in the same change and keep transport-level preview
  behavior stable.
- **Errors may accidentally reveal local paths.** Mitigation: centralize
  bounded error construction and assert redaction in tool and end-to-end tests.

## Migration Plan

1. Capture current scatter, line, and bar baselines and identify all private
   helper call sites before moving shared fit logic.
2. Add neutral Cartesian fit and geometry utilities with compatibility wrappers,
   then implement scatter frame, orientation, axis evidence, and calibration
   gating behind the new result contract.
3. Add series association, marker evidence flags, overlap/density/outlier
   handling, and source-sized overlay rendering.
4. Migrate review consumers, fixtures, tool tests, end-to-end trajectories,
   frontend mocks/types, and documentation; remove obsolete point-only
   assumptions after all call sites are covered.
5. Run focused scatter tests, the line/bar regression tests, the full Python
   suite, frontend build/smoke checks, and `git diff --check` in the Conda
   `agent` environment where applicable.
6. If a regression appears, revert the consumer migration and keep the neutral
   helper extraction isolated until the failing contract is understood; no
   persisted-data migration is required.
