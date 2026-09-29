## MODIFIED Requirements

### Requirement: RunExecutionState is reconstructed from Session-owned image facts
Figura SHALL build a read-only `RunExecutionState` for a target Run with exactly these top-level fields: `run_id`, `available_attachments`, `panels`, and `measurements`. `available_attachments` SHALL contain each distinct attachment referenced by an earlier terminal Run in the same Session or by the target Run, ordered by Run ordinal and then by the persisted attachment order, with duplicate attachment IDs retained only at their first occurrence. Each attachment inventory item SHALL contain its opaque `attachment_id` and sanitized display `filename`. `panels` SHALL contain every Panel with a committed successful tool result in the same Session, ordered by originating Run ordinal and Panel creation order. A Panel SHALL expose `panel_id`, originating `run_id`, `source_attachment_id`, `name`, and normalized `points`. `measurements` SHALL contain each committed `measure_bars`, `measure_lines`, or `measure_scatter` outcome in the same Session whose source kind and ID resolve to an Attachment or Panel in the Session's authorized image inventory. Measurement observations SHALL be ordered by originating Run ordinal and tool-call order. Each observation SHALL expose `run_id`, `call_id`, `attempt_id`, `tool_name`, `source_kind`, `source_id`, and `outcome`, plus exactly one of the bounded `result` or structured `error` associated with that outcome. Figura SHALL derive this projection from Run inputs, attachment metadata, durable Panel records, and committed tool-execution facts; it SHALL NOT persist a second mutable copy or truncate committed measurement observations.

#### Scenario: Build an inventory across earlier and current Runs
- **WHEN** a target Run has earlier terminal Runs in the same Session and multiple referenced attachments in its own input
- **THEN** `RunExecutionState.available_attachments` contains every distinct referenced attachment in Run and input order, including prior-Run attachments, without resolving or embedding image bytes

#### Scenario: Include only Panels whose creation result committed
- **WHEN** Panel metadata and image files exist but the corresponding `decompose_chart_image` result is not committed
- **THEN** `RunExecutionState.panels` omits those Panels until the successful tool result is committed

#### Scenario: Project all committed Cartesian measurement outcomes
- **WHEN** a `measure_bars`, `measure_lines`, or `measure_scatter` result for an authorized source is committed in the target Run or an earlier terminal Run in the same Session
- **THEN** `RunExecutionState.measurements` contains its source identity, call and attempt identities, outcome, and complete committed result or error in Run and tool-call order

#### Scenario: Omit measurement calls without a committed outcome
- **WHEN** a measurement attempt has started but no tool result has committed
- **THEN** `RunExecutionState.measurements` contains no observation for that attempt

#### Scenario: Exclude attachments, Panels, and measurements owned by another Session
- **WHEN** the store contains image or tool-result records from another Session
- **THEN** none of their IDs, metadata, or measurement observations appear in the target Run's `RunExecutionState`

### Requirement: Image bytes are loaded only by explicit tool calls
Figura SHALL register a `load_image` tool whose input contains `source_kind` (`attachment` or `panel`) and the corresponding opaque `source_id`. The tool SHALL resolve only an attachment present in the target Run's `RunExecutionState.available_attachments` or a Panel in `RunExecutionState.panels`, and SHALL verify Session ownership before reading bytes. A successful `load_image` result SHALL contain only the source kind, opaque ID, display name, and image dimensions; image bytes SHALL remain outside durable tool results. A model request SHALL include original image bytes only for successful `load_image` calls in the immediately preceding fully committed tool batch, in tool-call order, with duplicate source IDs included once. For a fully committed batch containing successful `measure_bars`, `measure_lines`, or `measure_scatter` calls, Figura SHALL additionally include one deterministic annotated image per successful measurement call in tool-call order. Each annotated image SHALL be reconstructed from the authorized selected source and its committed JSON result; image bytes and overlays SHALL NOT be persisted in the tool result or `RunExecutionState`. The initial request and requests following any other tool batch SHALL contain no image bytes.

#### Scenario: Start a Run with multiple images
- **WHEN** a Run references multiple images and the checkpoint points to its initial model action
- **THEN** the model receives a text inventory of all available attachment IDs and names, and no attachment image bytes

#### Scenario: Load multiple images in one tool batch
- **WHEN** the model calls `load_image` for multiple authorized attachments or Panels in one response and all tool results commit
- **THEN** the next Provider request contains each successfully loaded original image once in tool-call order, with its ID and name identified in user-role text content

#### Scenario: Load an image from an earlier Run
- **WHEN** the model calls `load_image` with an earlier terminal Run's attachment ID in the same Session inventory
- **THEN** Figura resolves that attachment and provides its bytes to the next model request without automatically resending it in later requests

#### Scenario: Return annotated images after a measurement batch
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful Cartesian measurement calls
- **THEN** the next Provider request contains the matching JSON tool observations and one annotated selected-source image per successful measurement call, in tool-call order, with each image identified by tool name and call ID

#### Scenario: Do not repeat old measurement overlays
- **WHEN** the immediately preceding completed tool batch contains no successful Cartesian measurement call
- **THEN** the Provider request contains no annotated measurement images from earlier batches or Runs

#### Scenario: Reject an image outside the RunExecutionState inventory
- **WHEN** a tool call requests an unknown, unreferenced, or cross-Session attachment or Panel
- **THEN** Figura returns a bounded tool failure and provides no image bytes to the Provider

#### Scenario: Fail before provider dispatch when a measurement source cannot be resolved
- **WHEN** a successful measurement result requires an annotated image but its authorized selected source bytes cannot be resolved while assembling the next request
- **THEN** Figura fails before claiming the Provider attempt and sends no request

#### Scenario: Enforce provider image bounds for loaded and annotated images
- **WHEN** the original images and annotated images for the immediately preceding committed batch exceed a Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails before claiming or dispatching a Provider attempt

#### Scenario: Read image bytes after the tool file has disappeared
- **WHEN** a `load_image` result committed but its source bytes cannot be resolved while assembling the next request
- **THEN** Figura fails before claiming the Provider attempt and sends no request
