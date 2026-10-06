## Why

Figura currently measures and renders only bar, line, scatter, and pie charts, while its two-point-shape ChartSpec cannot represent several common chart families. This change establishes one complete, typed path for the ten selected families so chart measurement, assembly, and rendering share a coherent contract instead of growing as disconnected tools.

## What Changes

- Add one model-facing `measure_chart` tool for bar, line, scatter/bubble, pie/donut, area, histogram, box plot, radar, heatmap, and treemap. The Agent selects the required `chart_type`; it uses `load_image` when visual classification is uncertain. The tool does not make hidden Provider calls or silently switch chart families.
- Keep family-specific measurement adapters behind the common tool and return a versioned common result envelope with typed family observations, geometry, calibration, uncertainty, status, and warnings.
- Introduce ChartSpec v2 with a strict typed dataset for each selected family and an appropriate coordinate-system contract. Extend ChartFigure assembly and PNG rendering to all ten types.
- Treat bubble as scatter with an optional size channel and donut as pie with an inner-radius option. Include only ordinary variants needed by these families; exclude combo/multi-axis, 3D, candlestick, funnel, rose, and other specialist chart types.
- **BREAKING:** New Runs expose `measure_chart` instead of the four separate `measure_bars`, `measure_lines`, `measure_scatter`, and `measure_pie` tools. The new contracts do not read or convert ChartSpec/Figure v1 or adapt old measurement results. No database backfill or legacy Registry executor is added; deployment must wait until Runs on the previous Registry are terminal.
- Keep measurement evidence in Run tool facts/resources and its Figure reference. ChartSpec remains chart content and does not absorb Run identity, source authorization, or evidence provenance.

## Capabilities

### New Capabilities
- `chart-family-measurement`: One measurement entry point and typed observations for all ten selected chart families.

### Modified Capabilities
- `bar-chart-measurement`: Remove the standalone model-facing bar tool contract; retain bar measurement as an internal adapter of `measure_chart`.
- `line-chart-measurement`: Remove the standalone model-facing line tool contract; retain line measurement as an internal adapter of `measure_chart`.
- `scatter-chart-measurement`: Remove the standalone model-facing scatter tool contract; retain scatter/bubble measurement as an internal adapter of `measure_chart`.
- `pie-chart-measurement`: Remove the standalone model-facing pie tool contract; retain pie/donut measurement as an internal adapter of `measure_chart`.
- `chart-spec-core`: Replace the v1 four-family model with the strict v2 ten-family model; v1 is unsupported by the new contract.
- `chart-figure-assembly`: Accept v2 ChartSpecs and measurement references from the unified tool; define the new Figure contract without v1 conversion.
- `chart-rendering`: Render every selected family through the v2 ChartFigure contract.
- `panel-image-observation`: Include unified chart-measurement results in the existing annotated-image feedback path.
- `run-execution-resources`: Reconstruct and expose the new unified measurement result and v2 Figure resources without adapting old result formats.

## Impact

Affected areas include `src/figura/tools/measurements/` and tool definitions, Agent image feedback and Run resource projection, `src/figura/charts/chartspec/`, `chartfigure/` and Figure assembly/render tools, the Gateway tool Registry, relevant prompting assets, tests, OpenSpec specifications, and Figura architecture documentation. No new database tables or data backfill are planned. Existing raw Run facts remain stored, but the new version does not promise typed reconstruction or rendering of legacy chart resources.
