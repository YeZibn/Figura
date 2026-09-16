## Context

See `proposal.md` for the motivation and scope. The current observation
package has useful but uneven shared helpers in `cartesian.py`. Line and
scatter each own frame logic, bars owns baseline fitting, pie imports several
generic helpers through a Cartesian-named module, and overlays repeat frame
and axis drawing. The existing sensors already preserve source-image
geometry and bounded evidence, so this change should reorganize those
responsibilities without introducing a new image-processing dependency or a
mandatory Agent tool sequence.

## Goals / Non-Goals

**Goals:**

- Define one chart-evidence foundation shared by bar, line, scatter, and pie.
- Keep coordinate semantics explicit and replaceable: Cartesian2D for axes and
  Polar2D for circular sectors.
- Keep mark detectors independent from one another and from OCR, transport,
  review, and frontend code.
- Provide one common evidence envelope while retaining mark-specific geometry.
- Make baseline, frame, transform, association, confidence, warnings, and
  overlays use the same source-image evidence.
- Migrate known consumers and tests in one coherent contract change.

**Non-Goals:**

- A universal detector that identifies every possible chart or mark.
- Perspective correction, 3D reconstruction, logarithmic/dual-axis support,
  or photographed-document understanding.
- Replacing the existing chart-specific measurement algorithms with a single
  generic geometry algorithm.
- A new Agent-facing layout tool or a fixed OCR-then-sensor workflow.
- Changing ChartSpec semantics or adding image evidence to persisted specs.

## Decisions

### 1. Use a neutral chart-evidence foundation

Common code will be organized conceptually into image/geometry primitives,
color evidence, association, quality, contract serialization, and base overlay
drawing. These modules return plain evidence data and do not import chart
detectors, `ToolResult`, Agent state, Review, or frontend modules.

The current `cartesian.py` will stop being the home for generic helpers. Image
size, color normalization, bounded points, confidence, IDs, and similar
utilities move to the neutral foundation. A compatibility facade may re-export
public helpers during migration, but sensors must depend only on the public
foundation boundary and not on private functions from another sensor.

Alternative considered: keep expanding `cartesian.py` as a shared utility file.
Rejected because it would continue to make pie and future coordinate models
appear Cartesian and would not prevent detector-specific logic from leaking
into the shared module.

### 2. Make coordinate systems adapters, not chart types

The foundation will expose a coordinate-context interface with source-image
frame geometry, transform evidence, and calibration status. A Cartesian2D
adapter supplies x/y axes, an origin or affine basis, tick transforms, and
zero-level evidence. A Polar2D adapter supplies center, radius, angular
orientation, and sector-angle support.

Coordinate adapters consume generic text evidence when available; they do not
call the OCR tool. A sensor may obtain OCR through the existing boundary and
pass snippets into the adapter, or proceed without them. This keeps OCR
replaceable and allows deterministic tests to inject evidence directly.

Alternative considered: force pie through an x/y frame so all results have
identical geometry. Rejected because it loses sector semantics and makes the
absence of Cartesian axes look like an error.

### 3. Separate layout, calibration, mark detection, and composition

Each specialized sensor follows the same internal shape without sharing its
mark algorithm:

```text
source image + optional evidence
        │
        ▼
coordinate context
        │
        ▼
mark detector(context)
        │
        ▼
association + quality
        │
        ▼
common envelope + mark-specific result + overlay
```

The bar detector keeps bar candidates, category/series grouping, stack
evidence, and baseline measurement. The line detector keeps traces, fragments,
markers, and anchored samples. The scatter detector keeps marker appearance,
overlap, density, and outlier evidence. The pie detector keeps sectors,
printed values, leader lines, and angular totals. None of these detectors
imports another detector.

### 4. Use a common envelope with stable mark-specific payloads

The canonical result will have a common evidence section containing image
size, coordinate-system/frame evidence, legend, series identities, confidence,
and warnings. Mark-specific payloads remain explicit and continue to carry
their useful geometry. Every item that belongs to a series references the
common stable series ID; pie sectors may use sector IDs and associations
without pretending to be Cartesian series.

The migration will remove duplicate or unused layout fields only after all
repository consumers are moved to the canonical envelope. Fields with
distinct measurement meaning, such as bar baseline, line trace, scatter point,
and pie sector geometry, are not collapsed into a generic polygon list.

### 5. Treat baseline as a mark measurement validated by the coordinate context

For bars, the shared context supplies candidate axes, origin, orientation, and
zero-level evidence. The bar detector compares its fitted baseline with that
evidence. A visible axis is preferred; a bar-edge fit is a fallback or a
cross-check. Material disagreement lowers confidence and produces a warning;
it does not silently replace the axis with a visually convenient line.

This preserves horizontal, mixed-sign, stacked, and small-rotation behavior
while making the source of baseline evidence explicit.

### 6. Render common and specialized overlays in two layers

The overlay path will have a common renderer for source image size, frame,
coordinate evidence, IDs, and warnings. Each sensor adds its own mark layer.
Both layers consume the already serialized geometry. Overlay code will not
rerun detection or infer a second baseline, frame, or transform.

### 7. Keep transport and review at the composition boundary

Sensors return the same `ToolResult` and `GeneratedImage` types after composing
the new evidence structure. Review code reads the public sensor result and
chart-specific payloads; it does not import foundation internals. Gateway,
preview, and Agent observation transport remain unchanged.

### Public result contract after migration

Each successful or inspectable chart observation exposes `data.evidence` with
the following stable fields:

```text
evidence.image_size       source width/height in pixels
evidence.coordinate_system cartesian_2d or polar_2d
evidence.frame            coordinate-model geometry, or null/partial evidence
evidence.legend           supplied legend/association evidence
evidence.series           stable series identities when applicable
evidence.confidence       bounded quality map with overall and component scores
evidence.warnings         bounded uncertainty messages
```

The top-level result continues to carry mark-specific payloads for the
transition: `bars` and `baseline`, `series`/`trace` and line points, scatter
points/overlaps, or pie `sectors`/`totals`. These payloads remain in source
image coordinates and are not replaced by a generic mark list. The old
`cartesian` import remains a compatibility facade; new detector code imports
generic primitives from `foundation` and coordinate behavior from
`coordinates`.

## Risks / Trade-offs

- **Shared-layout regressions affect several charts** → add fixture-level
  contract tests before migrating each sensor and run all existing sensor
  regressions after every migration stage.
- **A common envelope becomes too generic** → keep coordinate and mark payloads
  explicit, and require stable IDs rather than flattening all geometry.
- **OCR coupling reappears through convenience imports** → pass text evidence
  as data and keep OCR invocation in sensor orchestration only.
- **Baseline and axis evidence disagree** → retain both evidence sources,
  apply a confidence gate, and report the disagreement instead of choosing
  silently.
- **Old consumers read divergent fields** → search all repository call sites,
  migrate them together, and retain only deliberately documented compatibility
  aliases during the transition.
- **Richer overlays approach transport limits** → keep one bounded,
  source-sized overlay per observation and reuse existing image normalization.

## Migration Plan

1. Capture current bar, line, scatter, and pie result shapes and add shared
   contract fixtures for complete, partial, rotated, and unsupported evidence.
2. Extract neutral foundation models and utilities, with the existing
   sensor-facing helpers delegating to them during the transition.
3. Add Cartesian2D and Polar2D coordinate contexts and generic association/
   quality composition without changing mark algorithms yet.
4. Migrate pie first to prove generic foundation helpers no longer depend on a
   Cartesian-named module; then migrate line and scatter to the shared frame
   and transform; migrate bars last so baseline validation can use the mature
   context.
5. Add the common overlay layer and update Review, fixtures, end-to-end tests,
   mocks, and documentation to consume the canonical envelope.
6. Remove stale duplicate helpers and unused fields after repository-wide
   call-site checks, then run focused tests, the full Python suite, frontend
   build/smoke checks, strict OpenSpec validation, and `git diff --check`.

Rollback is a source-level revert before archive. Observation payloads are
per-run evidence and do not require persisted-data migration.
