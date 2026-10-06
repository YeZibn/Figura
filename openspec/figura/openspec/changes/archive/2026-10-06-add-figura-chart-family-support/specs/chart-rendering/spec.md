## REMOVED Requirements

### Requirement: Render an accepted ChartFigure into one composite image
**Reason**: The existing rendering requirement only accepts the four-family v1 child set and must be replaced by ten-family ChartFigure v2 rendering.
**Migration**: Submit a ChartFigure v2 with supported ChartSpec v2 children and use the same explicit render reference workflow.

## ADDED Requirements

### Requirement: Render all selected chart families in a ChartFigure v2
Figura SHALL provide `render_chart_figure` for a successfully committed ChartFigure v2 identified by `{run_id, call_id}` in the target Session. It SHALL verify the complete Figure against its committed canonical digest and render ordered children into one composite PNG following `layout.columns`. It SHALL support `bar`, `line`, `scatter`, `pie`, `area`, `histogram`, `box_plot`, `radar`, `heatmap`, and `treemap`; scatter with a size channel SHALL render bubbles and pie with a positive inner radius SHALL render a donut. It SHALL NOT support v1 Figures, v1 ChartSpecs, combo/multi-axis charts, or the excluded specialist types. Render dimensions, palettes, typography, and layout policy SHALL be fixed server-side; callers SHALL NOT supply arbitrary renderer parameters.

The Figure title, child titles, plots, axes/legends, and optional captions SHALL remain inside the bounded canvas and SHALL NOT overlap in a successful result. Nonempty ChartSpec `source` and `note` text SHALL also be rendered within their chart's allocated region. A chart that cannot be laid out legibly SHALL return a bounded rendering failure. Pie and donut charts SHALL display slice labels and one-decimal percentages computed from each value divided by that chart's positive dataset total. A zero-valued slice's percentage label SHALL be omitted. Display rounding SHALL NOT modify input values or force rounded percentages to sum to exactly 100. The result SHALL contain exactly the Figure reference, Figure digest, PNG SHA-256, media type `image/png`, byte count, width, and height; it SHALL NOT contain image bytes, filesystem paths, or another Figure/render identity.

#### Scenario: Render one Figure containing all supported families
- **WHEN** a valid v2 Figure contains children from the ten supported families
- **THEN** the output PNG preserves child order and declared columns and the result digest matches the accepted Figure

#### Scenario: Render bubble and donut variants
- **WHEN** a scatter child has a size channel or a pie child has a positive inner radius
- **THEN** the renderer produces visible bubble-size differences or a donut hole without changing the family identity

#### Scenario: Reject an unsupported family or old Figure
- **WHEN** the reference resolves to v1 content, an invalid v2 child, or a chart family outside the ten types
- **THEN** rendering fails with a bounded error and exposes no image bytes

#### Scenario: Keep every child legible within the image bounds
- **WHEN** a valid v2 Figure's titles, labels, legends, or captions cannot fit without clipping or overlap
- **THEN** Figura reports a bounded render failure rather than committing a falsely successful PNG

#### Scenario: Persist image bytes privately
- **WHEN** a render succeeds
- **THEN** `ToolResultFact` contains bounded render metadata only and PNG bytes remain in private managed storage
