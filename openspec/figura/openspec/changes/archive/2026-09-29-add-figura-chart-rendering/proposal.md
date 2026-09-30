## Why

`assemble_chart_figure` now accepts and retains a validated multi-chart Figure, but Figura cannot yet turn that content into an image. The next change should make the Figure viewable, let the Agent inspect the rendered result in the next ReAct step, and expose the committed image in the web workspace.

## What Changes

- Add a `render_chart_figure` tool that accepts a reference to a successfully assembled Figure and produces one composite PNG for its ordered charts.
- Store PNG bytes in private managed storage, keyed by the rendering Run and tool-call identity; keep only bounded metadata in the committed tool result and derive render observations from existing Run facts.
- Add a read-only `RunExecutionState.chart_renders` projection for committed render outcomes, without introducing another durable Run field or a separate render table.
- Include a successfully rendered image in the next Provider request only when the immediately preceding fully committed tool batch rendered it; keep older render summaries textual.
- Add Session-scoped Gateway metadata and image-content access, then display committed chart previews under their originating Runs in Figura mode.

Figure assembly remains responsible only for validating and retaining Figure content. This change does not add chart editing, semantic review, publication, retry controls, model-selected render settings, or a second copy of Figure content.

## Capabilities

### New Capabilities
- `chart-rendering`: Render an accepted ChartFigure as a private, durable composite PNG and expose committed render outcomes to Agent and Web consumers.

### Modified Capabilities
- `panel-image-observation`: Extend the derived `RunExecutionState` inventory with committed chart-render observations.
- `agent-react-execution`: Let the Agent visually inspect a chart image produced in its immediately preceding committed tool batch.
- `figura-web-gateway`: Expose safe metadata and Session-scoped content reads for committed chart renders.
- `figura-web-client`: Display committed chart-render previews in Figura mode.

## Impact

Affected areas include `src/figura/charts/chartfigure/`, the tool implementation and registry, private image storage under Sources, `RunExecutionState` and Provider request assembly, Figura Gateway projections/routes, and the Figura frontend API and run output presentation. Existing ChartFigure assembly and generic durable tool facts remain the sources of Figure content and render-result metadata. No legacy ChartAgent capability or contract is changed.
