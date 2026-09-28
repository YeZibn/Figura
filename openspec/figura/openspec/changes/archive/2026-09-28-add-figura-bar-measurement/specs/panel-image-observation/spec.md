## MODIFIED Requirements

### Requirement: RunExecutionState is reconstructed from Session-owned image facts
Figura SHALL build a read-only `RunExecutionState` for a target Run with exactly these top-level fields: `run_id`, `available_attachments`, `panels`, and `measurements`. `available_attachments` SHALL contain each distinct attachment referenced by an earlier terminal Run in the same Session or by the target Run, ordered by Run ordinal and then by the persisted attachment order, with duplicate attachment IDs retained only at their first occurrence. Each attachment inventory item SHALL contain its opaque `attachment_id` and sanitized display `filename`. `panels` SHALL contain every Panel with a committed successful tool result in the same Session, ordered by originating Run ordinal and Panel creation order. A Panel SHALL expose `panel_id`, originating `run_id`, `source_attachment_id`, `name`, and normalized `points`. `measurements` SHALL contain each committed `measure_bars` outcome in the same Session whose source kind and ID resolve to an Attachment or Panel in the Session's authorized image inventory. Measurement observations SHALL be ordered by originating Run ordinal and tool-call order. Each observation SHALL expose `run_id`, `call_id`, `attempt_id`, `tool_name`, `source_kind`, `source_id`, and `outcome`, plus exactly one of the bounded `result` or structured `error` associated with that outcome. Figura SHALL derive this projection from Run inputs, attachment metadata, durable Panel records, and committed tool-execution facts; it SHALL NOT persist a second mutable copy or truncate committed measurement observations.

#### Scenario: Build an inventory across earlier and current Runs
- **WHEN** a target Run has earlier terminal Runs in the same Session and multiple referenced attachments in its own input
- **THEN** `RunExecutionState.available_attachments` contains every distinct attachment in Run and input order, including prior-Run attachments, without resolving or embedding image bytes

#### Scenario: Include only Panels whose creation result committed
- **WHEN** Panel metadata and image files exist but the corresponding `decompose_chart_image` result is not committed
- **THEN** `RunExecutionState.panels` omits those Panels until the successful tool result is committed

#### Scenario: Project committed measurement outcomes across Runs
- **WHEN** a `measure_bars` result for an authorized source is committed in the target Run or an earlier terminal Run in the same Session
- **THEN** `RunExecutionState.measurements` contains its source identity, call and attempt identities, outcome, and complete committed result or error in Run and tool-call order

#### Scenario: Omit measurement calls without a committed outcome
- **WHEN** a `measure_bars` attempt has started but no tool result has committed
- **THEN** `RunExecutionState.measurements` contains no observation for that attempt

#### Scenario: Exclude attachments, Panels, and measurements owned by another Session
- **WHEN** the store contains image or tool-result records from another Session
- **THEN** none of their IDs, metadata, or measurement observations appear in the target Run's `RunExecutionState`
