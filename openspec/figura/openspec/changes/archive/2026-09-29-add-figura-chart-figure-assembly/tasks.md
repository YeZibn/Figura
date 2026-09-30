## 1. Unify the Charts content domain

- [x] 1.1 Move `src/figura/chartspec/` into `src/figura/charts/`, update every source and test import, and remove the old package without a compatibility façade.
- [x] 1.2 Add immutable `ChartFigure`, `FigureLayout`, `ChartFigureItem`, and `MeasurementRef` values with the exact fields and bounds in the chart-figure-assembly spec.
- [x] 1.3 Add strict Figure schemas, parsing, canonical serialization, and digest support; reject unknown fields, duplicate keys, invalid child specs, and content over 64 KiB.
- [x] 1.4 Add pure Figure validation for chart IDs, child count, layout, reference shape, and existing nested ChartSpec semantics, with bounded field-path errors.
- [x] 1.5 Add focused model, codec, and validator coverage for all four chart types, multiple children, canonical ordering, defaults, and invalid input.

## 2. Assemble and persist Figures through Tools and Runtime

- [x] 2.1 Add the `assemble_chart_figure` tool definition with strict input/result schemas and a compact successful result containing the Figure reference, canonical digest, title, and ordered child summaries.
- [x] 2.2 Resolve every supplied measurement reference against a fresh same-Session execution-state projection; accept only committed successful measurement results and reject the complete Figure when any reference fails.
- [x] 2.3 Register the tool as `replay_safe` under `figura-web-v5`; retain complete input and result through the existing Runtime tool facts without adding a table or fact kind.
- [x] 2.4 Add handler coverage for valid references, empty references, failed/uncommitted/unknown/cross-Session references, bounded errors, digest stability, and Runtime fact persistence.

## 3. Project accepted Figures into Agent context

- [x] 3.1 Add the Figure summary projection to `RunExecutionState`, reconstructed from successful assembly call/result pairs across earlier terminal Runs and the target Run in Run/tool-call order.
- [x] 3.2 Extend the state contract to exactly five top-level fields and cover ordering, current-Run entries, prior-Run entries, failed/uncommitted exclusion, and Session isolation.
- [x] 3.3 Add the Figure reference and compact summary inventory to every Provider request without duplicating full ChartFigure data or truncating accepted entries.
- [x] 3.4 Add request-builder coverage proving that the model can address an earlier Run's Figure while full Figure content remains in ordinary tool-call history.

## 4. Update documentation and validate the change

- [x] 4.1 Update `docs/figura/charts.md` and `docs/figura-implementation-overview.md` to describe the unified Charts domain, complete Figure fields, Runtime fact ownership, state projection, and rendering/preview boundaries.
- [x] 4.2 Run the focused Charts, Tools, Runtime, and Agent tests, then the Figura test suite; run `openspec validate add-figura-chart-figure-assembly --store figura` and `git diff --check`.
