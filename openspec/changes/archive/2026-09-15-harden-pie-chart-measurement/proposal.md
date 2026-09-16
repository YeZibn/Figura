## Why

`extract_pie_slices` currently works for clean, non-donut fixtures, but its
geometry and association logic is still based on a near-circle heuristic,
fixed radial samples, and a right-side legend assumption. It can therefore
lose sector boundaries or fabricate confidence when the pie is translated,
rotated, partially occluded, has narrow or similar-colored sectors, or uses a
different label layout. The bar, line, and scatter sensors have just adopted
evidence-driven measurement contracts, so the pie sensor should receive the
same hardening treatment before the project expands to additional chart
families.

## What Changes

- Replace the pie sensor's ad-hoc geometry output with a unified source-image
  evidence contract for image size, orientation/transform, plot region,
  circular geometry, sectors, labels, confidence, and warnings.
- Infer the pie region and center/radius from bounded image evidence instead
  of treating a fixed color-component envelope and fixed radial samples as
  ground truth.
- Preserve sector boundary support, angular residuals, color evidence, and
  partial coverage so ratios are emitted as semantic values only when the
  evidence passes explicit quality gates.
- Make sector IDs and angle conventions deterministic across translation,
  supported image rotation, resizing, anti-aliasing, separator gaps, narrow
  sectors, and similar colors.
- Expand legend and OCR association evidence to support labels around the
  chart, external labels, and unresolved or ambiguous associations without
  silently guessing.
- Update the source-sized pie overlay to draw measured geometry, sector IDs,
  boundaries, ratios, associations, and material uncertainty using the same
  source-image coordinate convention as detection and serialization.
- Add bounded handling for partial, occluded, perspective, elliptical, 3D,
  donut, non-pie, malformed, missing, and unauthorized inputs without
  fabricating complete pie measurements or exposing local paths.
- Migrate pie review consumers, fixtures, tests, Agent-loop assertions,
  frontend mock observations, and chart-understanding documentation to the
  hardened contract while preserving the existing preview and observation
  transport.
- **BREAKING** Replace legacy pie result assumptions such as direct `circle`,
  flat sector angle/ratio fields, and unconditional association confidence
  with explicit geometry, measure, association, and uncertainty structures.
- Keep the scope to hardened ordinary two-dimensional pie charts; donut,
  exploded, nested, and fully perspective/3D chart support remain bounded
  unsupported cases for a later chart-variant change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-understanding`: strengthen pie-sector extraction with inferred
  source geometry, rotation/layout tolerance, evidence-gated ratios,
  explicit label/legend associations, bounded uncertainty, and source-sized
  visual evidence.

## Impact

- Pie sensor and overlay code under
  `src/chartagent/tools/chart/observation/`.
- Pie-related generated-chart review comparisons in
  `src/chartagent/review/manager.py`.
- Chart fixtures, tool tests, attachment-boundary tests, and Agent-loop
  acceptance tests under `tests/`.
- Frontend mock trace/observation payloads and the pie sections of
  `openspec/specs/chart-understanding/spec.md` and repository documentation.
- No new runtime dependency, Gateway route, database migration, or persisted
  data migration is planned. Python commands and OCR-backed tests continue to
  use the Conda `agent` environment with RapidOCR.
