## 1. ChartSpec v2 and ChartFigure v2 contracts

- [x] 1.1 Replace the four-family ChartSpec model/schema/codec with the strict v2 envelope, canonical serialization, duplicate-key rejection, and documented payload/item/text bounds.
- [x] 1.2 Implement deterministic semantic validation for all ten typed datasets, coordinate-system matching, numeric domains, and family-specific invariants.
- [x] 1.3 Replace the ChartFigure v1 model/codec/validator with v2 children, layout, measurement references, canonical digest, and complete-Figure byte validation.

## 2. Unified chart measurement

- [x] 2.1 Add the `measure_chart` ToolDefinition, closed input/result schemas, shared v2 result models, authorized-source resolution, scope handling, and explicit family router.
- [x] 2.2 Refactor the existing bar, line, scatter, and pie algorithm cores into internal family adapters that emit the v2 observation union; support bubble and donut variants.
- [x] 2.3 Implement area and histogram sensors with family-specific boundaries, axes, gaps/bins, calibration, uncertainty, and bounded observations.
- [x] 2.4 Implement box-plot and radar sensors with typed quartile/whisker and spoke/radial observations, preserving null values when calibration is unavailable.
- [x] 2.5 Implement heatmap and treemap sensors with typed cell/tree geometry, labels, color/value uncertainty, containment, and area observations.
- [x] 2.6 Enforce shared status, confidence, warnings, truncation, pixel-coordinate, result-bound, and no-auto-retry behavior across all ten adapters.

## 3. Figure rendering

- [x] 3.1 Add deterministic rendering for bar, line, scatter/bubble, area, histogram, and box-plot ChartSpec v2 datasets.
- [x] 3.2 Add deterministic rendering for pie/donut, radar, heatmap, and treemap ChartSpec v2 datasets.
- [x] 3.3 Integrate all ten renderers with the shared Figure grid/layout, fixed server-side style, bounded text placement, render integrity checks, and bounded failure behavior.

## 4. Run, Agent, and Gateway integration

- [x] 4.1 Update `assemble_chart_figure` to parse and validate v2 Figures and resolve only successful committed `measure_chart` references in the authorized same-Session prefix.
- [x] 4.2 Update execution-state schemas, typed resource projection, Provider prompt inventory, and measurement annotation reconstruction for the v2 result union; leave legacy facts uninterpreted as v2 resources.
- [x] 4.3 Bump the Gateway Registry to v9, register `measure_chart`, remove the four public measurement definitions, and update Agent guidance, tool descriptions, and timeline summaries.

## 5. Verification and release readiness

- [x] 5.1 Add fixtures and focused tests for every family, including uncertain calibration, unsupported geometry, excluded scope, truncation, bubble/donut variants, and value-preservation rules.
- [x] 5.2 Add round-trip, strict rejection, Figure assembly/render, Run resource, annotated-image, recovery, and Provider tool-schema tests for the v2 path.
- [x] 5.3 Verify v1 ChartSpec/Figure and old measurement references are rejected by the new contract, and the new Registry exposes no old measurement aliases or compatibility executor.
- [x] 5.4 Update Figura tool, architecture, and usage documentation to describe the ten-family v2 contracts and clean Registry cutover.
- [x] 5.5 Before activating v9, verify every v8-bound Run is terminal; run the complete Figura test suite and a mixed-family render smoke check as the release gate.
