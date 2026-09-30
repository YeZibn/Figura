## MODIFIED Requirements

### Requirement: RunExecutionState is reconstructed from Session-owned image facts
Figura SHALL build a read-only `RunExecutionState` for a target Run with exactly these top-level fields: `run_id`, `available_attachments`, `panels`, `measurements`, `chart_figures`, and `chart_renders`. `available_attachments` SHALL contain each distinct attachment referenced by an earlier terminal Run in the same Session or by the target Run, ordered by Run ordinal and then by the persisted attachment order, with duplicate attachment IDs retained only at their first occurrence. Each attachment inventory item SHALL contain its opaque `attachment_id` and sanitized display `filename`. `panels` SHALL contain every Panel with a committed successful tool result in the same Session, ordered by originating Run ordinal and Panel creation order. A Panel SHALL expose `panel_id`, originating `run_id`, `source_attachment_id`, `name`, and normalized `points`. `measurements` SHALL contain each committed `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie` outcome in the same Session whose source kind and ID resolve to an Attachment or Panel in the Session's authorized image inventory. Measurement observations SHALL be ordered by originating Run ordinal and tool-call order. Each observation SHALL expose `run_id`, `call_id`, `attempt_id`, `tool_name`, `source_kind`, `source_id`, and `outcome`, plus exactly one of the bounded `result` or structured `error` associated with that outcome. `chart_figures` SHALL contain each successfully committed `assemble_chart_figure` result in the same Session, ordered by originating Run ordinal and tool-call position. Each Figure inventory item SHALL expose its `figure_ref` (`run_id` and `call_id`), `figure_digest`, Figure `title`, and ordered child chart summaries (`chart_id`, `chart_type`, and `title`). `chart_renders` SHALL contain each committed successful or failed `render_chart_figure` outcome whose `figure_ref` resolves to an accepted Figure in the same Session, ordered by originating Run ordinal and tool-call position. Each render observation SHALL expose `run_id`, `call_id`, `attempt_id`, `figure_ref`, and `outcome`, plus exactly one of the bounded success `result` or structured `error`; its successful result SHALL contain `figure_digest`, `image_sha256`, `media_type`, `byte_count`, `width`, and `height`. Figura SHALL derive these projections from Run inputs, attachment metadata, durable Panel records, and committed tool-execution facts; it SHALL NOT persist a second mutable copy or truncate committed measurement, Figure, or render observations.

#### Scenario: Build an inventory across earlier and current Runs
- **WHEN** a target Run has earlier terminal Runs in the same Session and multiple referenced attachments in its own input
- **THEN** `RunExecutionState.available_attachments` contains every distinct referenced attachment in Run and input order, including prior-Run attachments, without resolving or embedding image bytes

#### Scenario: Include only Panels whose creation result committed
- **WHEN** Panel metadata and image files exist but the corresponding `decompose_chart_image` result is not committed
- **THEN** `RunExecutionState.panels` omits those Panels until the successful tool result is committed

#### Scenario: Project all committed measurement outcomes
- **WHEN** a `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie` result for an authorized source is committed in the target Run or an earlier terminal Run in the same Session
- **THEN** `RunExecutionState.measurements` contains its source identity, call and attempt identities, outcome, and complete committed result or error in Run and tool-call order

#### Scenario: Omit measurement calls without a committed outcome
- **WHEN** a measurement attempt has started but no tool result has committed
- **THEN** `RunExecutionState.measurements` contains no observation for that attempt

#### Scenario: Include an accepted Figure from the Session history
- **WHEN** an `assemble_chart_figure` call has a committed successful result in the target Run or an earlier terminal Run in the same Session
- **THEN** `RunExecutionState.chart_figures` contains its Run-scoped reference, digest, Figure title, and ordered chart summaries

#### Scenario: Omit an uncommitted or failed Figure
- **WHEN** Figure arguments exist but the tool call has no committed successful result
- **THEN** `RunExecutionState.chart_figures` contains no entry for that call

#### Scenario: Include a committed render outcome for an accepted Figure
- **WHEN** a `render_chart_figure` call referencing an accepted same-Session Figure has a committed success or failure in the target Run or an earlier terminal Run
- **THEN** `RunExecutionState.chart_renders` contains the render call identity, Figure reference, outcome, and complete bounded result or structured error in Run and tool-call order

#### Scenario: Omit incomplete or unresolved render calls
- **WHEN** a render attempt has started without a committed result, or its Figure reference is malformed, unresolved, or unauthorized
- **THEN** `RunExecutionState.chart_renders` contains no observation for that call

#### Scenario: Exclude attachments, Panels, measurements, and Figures owned by another Session
- **WHEN** the store contains image or tool-result records from another Session
- **THEN** none of their IDs, metadata, observations, or Figure summaries appear in the target Run's `RunExecutionState`
