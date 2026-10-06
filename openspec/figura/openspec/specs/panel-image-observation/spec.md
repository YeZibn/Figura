# panel-image-observation Specification

## Purpose
Provides a Run with a reconstructable inventory of the Session's referenced images, on-demand image reading, and durable independent Panel images created from model-proposed regions.

## Requirements

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

### Requirement: Session deletion removes owned Panel images and records
Figura SHALL remove every Panel record and private Panel PNG owned by a permanently deleted Session. Panel metadata and content reads for the deleted Session SHALL fail as not found. If the Session deletion transaction rolls back, staged Panel images SHALL be restored and remain readable.

#### Scenario: Remove a Session's Panels
- **WHEN** a Session with committed Panels is permanently deleted
- **THEN** its Panel metadata and PNG files are unavailable and Panels belonging to other Sessions remain readable

#### Scenario: Restore Panels after a failed Session deletion
- **WHEN** the Session deletion transaction fails after Panel files have been staged
- **THEN** Figura restores the staged Panel files and retains their metadata and readable content

### Requirement: Image bytes enter model requests only through explicit observation calls
Figura SHALL register `load_image` with authorized `source_kind` and opaque `source_id`. It SHALL verify Session ownership and return only the source kind, ID, display name, and dimensions; original bytes SHALL remain outside durable tool results. A Provider request SHALL include original image bytes only for successful `load_image` calls in the immediately preceding fully committed tool batch, in tool-call order, with duplicate source IDs included once. A fully committed batch containing successful `measure_chart` calls SHALL additionally include one deterministic annotated image per successful measurement call, reconstructed from its authorized selected source and complete result. Successful `extract_text` calls SHALL likewise include one matching transient OCR annotation. Image bytes and annotations SHALL NOT be persisted in resource catalogs or tool-result JSON. The initial request and requests after other tool batches SHALL contain no image bytes.

#### Scenario: Start a Run with multiple images
- **WHEN** a Run references multiple images and the checkpoint points to its initial model action
- **THEN** the model receives a text inventory of available image references and names, but no attachment image bytes

#### Scenario: Load multiple images in one tool batch
- **WHEN** successful `load_image` calls reference multiple authorized images in one fully committed batch
- **THEN** the next Provider request contains each original image once in call order with its ID and name in user-role text

#### Scenario: Load an image from an earlier Run
- **WHEN** `load_image` names an authorized image resource from an earlier terminal Run in the same Session
- **THEN** Figura provides its bytes to the next Provider request without resending it in later requests

#### Scenario: Return annotated images after a measurement batch
- **WHEN** the immediately preceding fully committed batch contains one or more successful `measure_chart` calls
- **THEN** the next Provider request contains the matching JSON observations and one annotated image per call, identified by tool name and call ID

#### Scenario: Return OCR annotations after an OCR batch
- **WHEN** the immediately preceding fully committed batch contains successful `extract_text` calls
- **THEN** the next Provider request contains the matching OCR observations and one transient annotated image per call

#### Scenario: Do not repeat old overlays
- **WHEN** the immediately preceding batch contains no successful OCR or `measure_chart` call
- **THEN** no annotation from an earlier batch or Run is attached

#### Scenario: Reject an image outside the resource catalog
- **WHEN** a call requests an unknown, unreferenced, or cross-Session source
- **THEN** Figura returns a bounded failure and provides no image bytes

#### Scenario: Fail before Provider dispatch if an observation image is unavailable
- **WHEN** a successful OCR or measurement result requires annotation but its authorized source cannot be resolved
- **THEN** request preparation fails before claiming a Provider attempt and sends no request

#### Scenario: Enforce Provider image bounds
- **WHEN** original and annotated images exceed a Provider image count, per-image size, aggregate size, or other request bound
- **THEN** request preparation fails before Provider dispatch

#### Scenario: Read an image after its source file disappears
- **WHEN** a `load_image` result committed but its source bytes cannot be resolved for the next request
- **THEN** request preparation fails and sends no image
