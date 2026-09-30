## Why

Figura currently validates one `ChartSpecData` at a time, but has no model-facing contract for combining several charts into one canvas or retaining that accepted composition across Runs. Adding a `ChartFigure` aggregate now creates the content and execution boundary needed before rendering and preview are introduced in later changes.

## What Changes

- Establish one `charts` code domain that owns the existing `ChartSpecData` model and the new `ChartFigure` model, parser, serializer, and validators.
- Add an immutable `ChartFigure` canvas containing an ordered set of independently validated `ChartSpecData` children, a simple grid layout, and per-chart references to selected measurement results.
- Add a model-callable `assemble_chart_figure` tool that validates the complete canvas and all supplied measurement references atomically.
- Persist accepted Figure content through the existing Runtime tool-call facts and return a stable reference, canonical digest, and compact chart summary through the tool result.
- Extend the derived `RunExecutionState` with a Session-scoped inventory of successfully assembled Figures and make its summaries available in subsequent Provider prompts.
- Keep the Figure content and summary reconstructable from existing Run facts; do not introduce a Figure table or a parallel mutable store.
- Leave chart image rendering, generated-image storage, review, and Web preview for follow-up changes.

## Capabilities

### New Capabilities

- `chart-figure-assembly`: Define and assemble multi-chart canvas content, validate its chart and measurement references, and expose accepted Figures through durable Run facts and the execution-state projection.

### Modified Capabilities

- `panel-image-observation`: Extend the exact `RunExecutionState` field contract from four fields to include the committed `chart_figures` inventory.

## Impact

- Code ownership moves from `src/figura/chartspec/` to the broader `src/figura/charts/` domain; internal imports are updated without a compatibility package.
- New tool implementation belongs under `src/figura/tools/implementations/`; Figure inventory reconstruction and prompt projection belong to the Agent execution-state/request path.
- Runtime persistence continues to use `ToolCallFact.arguments_json` and `ToolResultFact`; no SQLite schema migration or new Runtime fact kind is required.
- Update the Charts component documentation, system overview, and affected tests when implementing. Existing `ChartSpecData` semantics and its 256 KiB standalone canonical serialization limit remain unchanged; the tool call remains subject to the Runtime's 64 KiB argument limit.
- No Gateway endpoint, frontend contract, generated PNG, rendering dependency, or publication state is introduced by this change.
