## Purpose

Provides a Run with a reconstructable inventory of the Session's referenced images, on-demand image reading, and durable independent Panel images created from model-proposed regions.

## ADDED Requirements

### Requirement: RunExecutionState is reconstructed from Session-owned image facts
Figura SHALL build a read-only `RunExecutionState` for a target Run with exactly these top-level fields: `run_id`, `available_attachments`, and `panels`. `available_attachments` SHALL contain each distinct attachment referenced by an earlier terminal Run in the same Session or by the target Run, ordered by Run ordinal and then by the persisted attachment order, with duplicate attachment IDs retained only at their first occurrence. Each attachment inventory item SHALL contain its opaque `attachment_id` and sanitized display `filename`. `panels` SHALL contain every Panel with a committed successful tool result in the same Session, ordered by originating Run ordinal and Panel creation order. A Panel SHALL expose `panel_id`, originating `run_id`, `source_attachment_id`, `name`, and normalized `points`. Figura SHALL derive this projection from Run inputs, attachment metadata, and durable Panel records; it SHALL NOT persist a second mutable copy of the execution state.

#### Scenario: Build an inventory across earlier and current Runs
- **WHEN** a target Run has earlier terminal Runs in the same Session and multiple referenced attachments in its own input
- **THEN** `RunExecutionState.available_attachments` contains every distinct referenced attachment in Run and input order, including prior-Run attachments, without resolving or embedding image bytes

#### Scenario: Include only Panels whose creation result committed
- **WHEN** Panel metadata and image files exist but the corresponding `decompose_chart_image` result is not committed
- **THEN** `RunExecutionState.panels` omits those Panels until the successful tool result is committed

#### Scenario: Exclude attachments and Panels owned by another Session
- **WHEN** the store contains image records from another Session
- **THEN** neither their IDs nor metadata appear in the target Run's `RunExecutionState`

### Requirement: Image bytes are loaded only by explicit tool calls
Figura SHALL register a `load_image` tool whose input contains `source_kind` (`attachment` or `panel`) and the corresponding opaque `source_id`. The tool SHALL resolve only an attachment present in the target Run's `RunExecutionState.available_attachments` or a Panel present in `RunExecutionState.panels`, and SHALL verify Session ownership before reading bytes. A successful tool result SHALL contain only the source kind, opaque ID, display name, and image dimensions; image bytes SHALL remain outside durable tool results. A model request SHALL include image bytes only for successful `load_image` calls in the immediately preceding fully committed tool batch, in tool-call order, with duplicate source IDs included once. The initial request and requests following any other tool batch SHALL contain no image bytes.

#### Scenario: Start a Run with multiple images
- **WHEN** a Run references multiple attachments and the checkpoint points to its initial model action
- **THEN** the model receives a text inventory of all available attachment IDs and names, and no attachment image bytes

#### Scenario: Load multiple images in one tool batch
- **WHEN** the model calls `load_image` for multiple authorized attachments or Panels in one response and all tool results commit
- **THEN** the next Provider request contains each successfully loaded image once in tool-call order, with its ID and name identified in user-role text content

#### Scenario: Load an image from an earlier Run
- **WHEN** the model calls `load_image` with an earlier terminal Run's attachment ID in the same Session inventory
- **THEN** Figura resolves that attachment and provides its bytes to the next model request without automatically resending it in later requests

#### Scenario: Reject an image outside the RunExecutionState inventory
- **WHEN** a tool call requests an unknown, unreferenced, or cross-Session attachment or Panel
- **THEN** Figura returns a bounded tool failure and provides no image bytes to the Provider

#### Scenario: Read image bytes after the tool file has disappeared
- **WHEN** a `load_image` result committed but its source bytes cannot be resolved while assembling the next request
- **THEN** Figura fails before claiming the Provider attempt and sends no request

### Requirement: Model-proposed polygons create one independent image per Panel
Figura SHALL register a `decompose_chart_image` tool accepting an authorized `attachment_id` and an ordered `panels` array. Each Panel input SHALL contain a bounded display `name` and a polygon `points` array; each point SHALL contain integer `x` and `y` coordinates in the inclusive range 0–1000, normalized to the source image width and height. Each polygon SHALL contain 3–64 points and each request SHALL contain 1–32 Panels. Figura SHALL perform only the structural and resource checks needed to execute the crop safely; it SHALL NOT semantically judge, repair, reorder, or resize the model-proposed regions, reject overlap between regions, or claim that a proposed Panel was visually reviewed. Figura SHALL create and retain an independent PNG image for every accepted Panel, crop it to the polygon's bounding box, and make pixels outside the polygon transparent. Each Panel SHALL have a unique opaque `panel_id` usable as its `load_image` identity.

#### Scenario: Create rectangular and nonrectangular Panels
- **WHEN** the model submits a four-point rectangle and a valid nonrectangular polygon for an authorized attachment
- **THEN** Figura creates two separate PNG images and two Panel records, with pixels outside each polygon transparent

#### Scenario: Accept overlapping model-proposed regions
- **WHEN** two valid submitted polygons overlap in the source image
- **THEN** Figura creates both Panels without applying a semantic overlap rejection or altering either polygon

#### Scenario: Reject a polygon that cannot be executed safely
- **WHEN** a region has fewer than three points, too many points, out-of-range coordinates, no drawable area, or would exceed the configured image resource limits
- **THEN** Figura returns a bounded validation failure and creates no Panel for that request

#### Scenario: Preserve the proposed geometry
- **WHEN** a valid polygon is accepted
- **THEN** the Panel record retains the exact normalized point sequence supplied by the model and the generated PNG corresponds to that polygon

### Requirement: Panel images and records are durable and idempotent
Figura SHALL persist Panel metadata in its SQLite data store and Panel PNG bytes in a private managed image directory outside Run tool-result JSON. The Panel record SHALL contain `panel_id`, `session_id`, originating `run_id`, `source_attachment_id`, `name`, and normalized `points`. `panel_id` SHALL also determine the managed image filename; local paths SHALL NOT be exposed in model results, Web DTOs, events, or ordinary logs. `decompose_chart_image` SHALL use the existing `idempotent_local_write` replay contract: replaying the same durable tool call SHALL return the original ordered Panel IDs and records without creating duplicates. Installation of image files and their metadata SHALL be staged and reconciled so interruption cannot make an uncommitted Panel visible or silently replace an already committed Panel image.

#### Scenario: Repeat a successfully committed decomposition
- **WHEN** durable tool recovery repeats a `decompose_chart_image` call whose Panel result has already committed
- **THEN** Figura returns the original ordered Panel IDs and does not create additional records or image files

#### Scenario: Recover an interrupted write before tool-result commit
- **WHEN** the process stops after a Panel image file is staged or installed but before its tool result commits
- **THEN** recovery reconciles the file and metadata state, and replay creates or returns exactly one Panel set for the same call

#### Scenario: Keep Panel content private
- **WHEN** a tool result, lifecycle event, log entry, or public metadata response is produced
- **THEN** it contains no image bytes, local path, API credential, or raw exception details

### Requirement: Panel access remains Session-scoped and source-bound
Figura SHALL permit Panel metadata and image reads only through the Panel's owning Session. Each Panel SHALL remain bound to the source attachment ID and immutable geometry recorded at creation. Figura SHALL retain source attachments referenced by Runs under the existing attachment-retention rule and SHALL NOT silently substitute another attachment or image for a missing Panel source or Panel image.

#### Scenario: Read a Panel in its owning Session
- **WHEN** Agent or the Web boundary requests a Panel using its owning Session ID and opaque Panel ID
- **THEN** Figura returns only that Panel's metadata or validated PNG bytes

#### Scenario: Reject cross-Session Panel access
- **WHEN** a caller requests a Panel through a different Session ID
- **THEN** Figura returns a bounded not-found or authorization failure without disclosing Panel metadata or bytes

#### Scenario: Detect a missing or corrupted Panel image
- **WHEN** Panel metadata exists but its managed image is missing, unsafe, or invalid
- **THEN** Figura reports a bounded storage or integrity failure and returns no replacement image
