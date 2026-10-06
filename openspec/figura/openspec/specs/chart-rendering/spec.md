# chart-rendering Specification

## Purpose

Turns an accepted ChartFigure into a private, durable PNG that the Agent can inspect and the owning Session can preview, while keeping Figure content and render artifacts addressable through existing Run facts.

## Requirements

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
