## REMOVED Requirements

### Requirement: Image bytes are loaded only by explicit tool calls
**Reason**: The observation feedback contract must name the unified measurement call rather than the removed four standalone tools.
**Migration**: New measurement calls use `measure_chart`; explicit `load_image` behavior and transient feedback remain unchanged.

## ADDED Requirements

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
