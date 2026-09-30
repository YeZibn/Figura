## Purpose

Turns an accepted ChartFigure into a private, durable PNG that the Agent can inspect and the owning Session can preview, while keeping Figure content and render artifacts addressable through existing Run facts.

## ADDED Requirements

### Requirement: Render an accepted ChartFigure into one composite image
Figura SHALL provide a model-callable `render_chart_figure` tool whose input contains exactly one `figure_ref` object with `run_id` and `call_id`. The reference SHALL resolve to a successfully committed `assemble_chart_figure` result in the target Session, including a Figure assembled earlier in the target Run or in an earlier Run in that Session. Figura SHALL load the complete Figure content from the referenced assembly call, verify it against the committed Figure digest, and render its ordered child charts into one composite PNG that follows the Figure's `layout.columns`. The renderer SHALL support every ChartSpec chart type accepted by ChartFigure: bar, line, scatter, and pie. Render dimensions and visual style SHALL use fixed server-side policy; callers SHALL NOT supply dimensions, theme, or other rendering options. The tool result SHALL contain exactly the referenced `figure_ref`, `figure_digest`, lowercase SHA-256 `image_sha256`, `media_type` equal to `image/png`, `byte_count`, `width`, and `height`. It SHALL NOT contain image bytes, filesystem paths, a new Figure ID, or a separate render ID.

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
`RunExecutionState` SHALL expose a read-only `chart_renders` tuple rebuilt from same-Session Run tool facts. It SHALL include committed `render_chart_figure` successes and failures only when the call references a Figure that is accepted in that Session. Each observation SHALL contain `run_id`, `call_id`, `attempt_id`, `figure_ref`, and `outcome`; a successful observation SHALL contain exactly one bounded `result` with `figure_digest`, `image_sha256`, `media_type`, `byte_count`, `width`, and `height`, while a failed observation SHALL contain exactly one structured `error`. Observations SHALL be ordered by Run ordinal and tool-call position. The projection SHALL exclude calls without a committed result, malformed or unresolved references, and facts from another Session. It SHALL NOT persist a second copy or truncate committed observations.

#### Scenario: Include a committed successful render
- **WHEN** a render call referencing an accepted same-Session Figure has a committed successful result
- **THEN** `RunExecutionState.chart_renders` contains its call identity, Figure reference, outcome, and complete bounded result metadata

#### Scenario: Include a committed render failure for an accepted Figure
- **WHEN** a render call references an accepted same-Session Figure and commits a structured failure
- **THEN** `RunExecutionState.chart_renders` contains its call identity, Figure reference, failed outcome, and structured error without image metadata

#### Scenario: Omit incomplete and unauthorized render calls
- **WHEN** a render call has no committed result, references an unknown Figure, or belongs to another Session
- **THEN** `RunExecutionState.chart_renders` contains no observation for that call
