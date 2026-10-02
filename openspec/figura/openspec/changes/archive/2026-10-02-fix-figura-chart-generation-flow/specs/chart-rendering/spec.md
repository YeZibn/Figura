## MODIFIED Requirements

### Requirement: Render an accepted ChartFigure into one composite image
Figura SHALL provide a model-callable `render_chart_figure` tool whose input contains exactly one `figure_ref` object with `run_id` and `call_id`. The reference SHALL resolve to a successfully committed `assemble_chart_figure` result in the target Session, including a Figure assembled earlier in the target Run or in an earlier Run in that Session. Figura SHALL load the complete Figure content from the referenced assembly call, verify it against the committed Figure digest, and render its ordered child charts into one composite PNG that follows the Figure's `layout.columns`. The renderer SHALL support every ChartSpec chart type accepted by ChartFigure: bar, line, scatter, and pie. Render dimensions and visual style SHALL use fixed server-side policy; callers SHALL NOT supply dimensions, theme, or other rendering options. The tool result SHALL contain exactly the referenced `figure_ref`, `figure_digest`, lowercase SHA-256 `image_sha256`, `media_type` equal to `image/png`, `byte_count`, `width`, and `height`. It SHALL NOT contain image bytes, filesystem paths, a new Figure ID, or a separate render ID.

The fixed server-side rendering policy SHALL allocate separate visible space for a nonempty Figure title, each child title, its plot, and nonempty source and note text. Successful output SHALL NOT clip these text regions at canvas boundaries or overlap titles with one another or the plot. This SHALL apply with or without a Figure title, for one through four children and all supported column layouts and chart types. Text SHALL be laid out within the existing image-size bounds; content that cannot be placed legibly within those bounds SHALL produce a bounded rendering failure rather than a falsely successful clipped image. No new model-supplied layout or style fields SHALL be accepted.

Pie charts SHALL display category labels and percentages computed from each value divided by the total valid dataset value, formatted with one decimal place and a percent sign. A zero-valued slice's percentage label SHALL be omitted. Display rounding SHALL NOT modify input values or force rounded percentages to sum to exactly 100.

#### Scenario: Render a Figure assembled in the target Run
- **WHEN** the target Run has a committed successful `assemble_chart_figure` result and the Agent calls `render_chart_figure` with its reference
- **THEN** Figura returns bounded metadata for one PNG containing all ordered child charts in the declared column layout
- **AND** the result's `figure_digest` matches the accepted Figure

#### Scenario: Render a Figure from an earlier Run in the same Session
- **WHEN** the reference identifies a successfully committed Figure from an earlier Run in the same Session
- **THEN** Figura renders that Figure without requiring the original attachment bytes or duplicating the Figure content

#### Scenario: Reject an unknown or unauthorized Figure reference
- **WHEN** the reference does not identify a successfully committed Figure in the target Session
- **THEN** the tool returns a bounded failure and creates no render artifact

#### Scenario: Reject corrupted or unrenderable Figure content
- **WHEN** the stored Figure content cannot be parsed, fails validation, or does not match its committed digest
- **THEN** the tool returns a bounded integrity or rendering failure and exposes no image bytes

#### Scenario: Render titled side-by-side pies
- **WHEN** a valid Figure contains a Chinese Figure title, two titled pie charts, and nonempty source and note text
- **THEN** the successful PNG visibly contains the total title, both child titles, both plots and each child's source and note without clipping or title overlap
- **AND** positive slices contain one-decimal percentage labels derived from their own chart's dataset

#### Scenario: Render a Figure without a total title
- **WHEN** a valid Figure omits its total title and retains child titles
- **THEN** the successful PNG shows all child titles inside the canvas without top-edge clipping

#### Scenario: Render mixed charts in a bounded grid
- **WHEN** a valid Figure contains bar, line, scatter and pie children with a two-column layout and multiline titles and captions
- **THEN** every successful child retains visible plot and text regions within the bounded canvas

#### Scenario: Report text that cannot fit
- **WHEN** accepted content cannot be rendered legibly without clipping or overlap inside the fixed image limits
- **THEN** rendering returns a bounded failure rather than committing a clipped successful image

#### Scenario: Preserve values when rounding pie percentages
- **WHEN** positive slice percentages round independently to a total other than exactly 100.0 percent, or the dataset contains a zero-valued slice
- **THEN** rendering preserves the source values and uses one-decimal positive percentages without an artificial correction or zero-slice percentage label
