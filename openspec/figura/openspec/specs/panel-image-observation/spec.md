# panel-image-observation Specification

## Purpose
Provides a Run with a reconstructable inventory of the Session's referenced images, on-demand image reading, and durable independent Panel images created from model-proposed regions.

## Requirements

### Requirement: Image bytes are loaded only by explicit tool calls
Figura SHALL register a `load_image` tool whose input contains `source_kind` (`attachment` or `panel`) and the corresponding opaque `source_id`. The tool SHALL resolve the corresponding typed image resource from the target Run's unified resource catalog, and SHALL verify Session ownership before reading bytes. A successful `load_image` result SHALL contain only the source kind, opaque ID, display name, and image dimensions; image bytes SHALL remain outside durable tool results. A model request SHALL include original image bytes only for successful `load_image` calls in the immediately preceding fully committed tool batch, in tool-call order, with duplicate source IDs included once. For a fully committed batch containing successful `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie` calls, Figura SHALL additionally include one deterministic annotated image per successful measurement call in tool-call order. For a fully committed batch containing successful `extract_text` calls, Figura SHALL include one matching transient OCR annotation per successful call. Each annotated image SHALL be reconstructed from the authorized selected resource and its committed JSON result; image bytes and overlays SHALL NOT be persisted in the resource catalog or tool result. The initial request and requests following any other tool batch SHALL contain no image bytes.

#### Scenario: Start a Run with multiple images
- **WHEN** a Run references multiple images and the checkpoint points to its initial model action
- **THEN** the model receives a text inventory of all available attachment resource references and names, and no attachment image bytes

#### Scenario: Load multiple images in one tool batch
- **WHEN** the model calls `load_image` for multiple authorized Attachment or Panel references in one response and all tool results commit
- **THEN** the next Provider request contains each successfully loaded original image once in tool-call order, with its ID and name identified in user-role text content

#### Scenario: Load an image from an earlier Run
- **WHEN** the model calls `load_image` with an earlier terminal Run's Attachment resource ID in the same Session catalog
- **THEN** Figura resolves that attachment and provides its bytes to the next model request without automatically resending it in later requests

#### Scenario: Return annotated images after a measurement batch
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful measurement calls
- **THEN** the next Provider request contains the matching JSON tool observations and one annotated selected-source image per successful measurement call, in tool-call order, with each image identified by tool name and call ID

#### Scenario: Return annotated images after an OCR batch
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful `extract_text` calls
- **THEN** the next Provider request contains the matching JSON tool observations and one annotated selected-source image per successful OCR call, in tool-call order, with each image identified by tool name and call ID

#### Scenario: Do not repeat old observation overlays
- **WHEN** the immediately preceding complete tool batch contains no successful OCR or measurement call
- **THEN** the Provider request contains no annotated OCR or measurement images from earlier batches or Runs

#### Scenario: Reject an image outside the resource catalog
- **WHEN** a tool call requests an unknown, unreferenced, or cross-Session Attachment or Panel reference
- **THEN** Figura returns a bounded tool failure and provides no image bytes to the Provider

#### Scenario: Fail before provider dispatch when an observation source cannot be resolved
- **WHEN** a successful OCR or measurement result requires an annotated image but its authorized selected resource image cannot be resolved while assembling the next request
- **THEN** Figura fails before claiming the Provider attempt and sends no request

#### Scenario: Enforce provider image bounds
- **WHEN** original and annotated images for the immediately preceding committed batch exceed a Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails before claiming or dispatching a Provider attempt

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
