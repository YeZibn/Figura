# chart-rendering Specification

## Purpose

Turns an accepted ChartFigure into a private, durable PNG that the Agent can inspect and the owning Session can preview, while keeping Figure content and render artifacts addressable through existing Run facts.

## Requirements

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
### Requirement: Persist render artifacts privately and replay local writes idempotently
Figura SHALL store each rendered PNG in private managed storage, outside tool-result JSON and public Run records. The artifact identity SHALL be the rendering tool call's `(run_id, call_id)` pair; its managed filename SHALL be derived safely from that identity and SHALL NOT be model-controlled. The PNG SHALL pass image-format, positive-dimension, and existing Figura image-size checks before success is committed. `render_chart_figure` SHALL use the existing `idempotent_local_write` replay contract: replay of the same Run/call SHALL return the original artifact and metadata rather than create a second artifact. Installation SHALL be atomic or staged so interruption before ToolResultFact commit cannot expose an uncommitted render. Missing, corrupted, or digest-mismatched content SHALL fail closed; Figura SHALL NOT silently replace it with another image.

#### Scenario: Keep image bytes out of durable tool facts
- **WHEN** a render result commits
- **THEN** `ToolResultFact` contains only the bounded render metadata and the PNG remains in private managed storage

#### Scenario: Replay a render after an uncertain local write
- **WHEN** recovery replays the same render Run/call after the image was installed but before its result committed
- **THEN** the handler returns the existing validated artifact and does not create a duplicate

#### Scenario: Keep an uncommitted artifact out of projections
- **WHEN** an image file exists without a committed successful tool result
- **THEN** Agent state and Web projections do not expose it as a completed render

#### Scenario: Reject corrupted or missing stored content
- **WHEN** a committed render references an image that is missing, invalid, or does not match its recorded SHA-256
- **THEN** Figura returns a bounded storage or integrity failure and does not substitute another artifact
### Requirement: Project committed render outcomes into RunExecutionState
Figura SHALL expose each committed render_chart_figure outcome in the target Run's read-only RunExecutionState.resources catalog as a typed chart_render resource, following the shared run-execution-resources contract. Its typed reference SHALL identify the originating run_id and call_id; its content SHALL retain attempt_id, the nullable typed Figure reference, and the committed outcome. A successful render resource SHALL be included only when its Figure reference resolves to an accepted Figure in the same Session and authorized Run prefix, and SHALL contain exactly one bounded result with figure_digest, image_sha256, media_type, byte_count, width, and height. A failed render resource SHALL retain exactly one structured error and any syntactically valid Figure reference; otherwise its Figure reference SHALL be null. Resources SHALL follow the catalog's deterministic order, exclude attempts without committed results and facts from another Session, and SHALL NOT create a second durable copy of render outcomes.

#### Scenario: Include a committed successful render
- **WHEN** a render call references an accepted same-Session Figure in the authorized prefix and commits a successful result
- **THEN** the resource catalog contains its typed reference, Figure reference, successful outcome, and complete bounded render metadata

#### Scenario: Include a committed render failure
- **WHEN** a render call commits a structured failure, including when its syntactically valid Figure reference is not accepted or resolvable
- **THEN** the resource catalog contains its typed reference, failed outcome, and structured error without successful image metadata

#### Scenario: Omit incomplete and unauthorized render calls
- **WHEN** a render call has no committed result, or its facts belong to another Session or fall outside the target Run's authorized prefix
- **THEN** the target Run's resource catalog contains no render resource for that call

### Requirement: Session deletion removes its private ChartFigure render files
Figura SHALL remove the private render PNG for every durable render tool call belonging to a permanently deleted Session. The operation SHALL leave render files belonging to other Sessions unchanged. If Session deletion rolls back, staged render files SHALL be restored; if the database deletion commits, staged files SHALL be permanently removed or retained only in inaccessible private cleanup storage for startup reconciliation.

#### Scenario: Remove committed render files with their Session
- **WHEN** a Session with one or more committed ChartFigure renders is permanently deleted
- **THEN** its render content endpoint no longer resolves those PNG files and another Session's render files remain readable

#### Scenario: Remove a staged render after a committed deletion
- **WHEN** the process stops after Session deletion commits but before staged render files are physically unlinked
- **THEN** startup reconciliation removes those inaccessible staged files and does not restore them

#### Scenario: Restore renders after a rolled-back deletion
- **WHEN** the Session deletion transaction fails after render files have been staged
- **THEN** Figura restores those files and their existing render reads continue to succeed
