## MODIFIED Requirements

### Requirement: Image bytes enter model requests only through explicit observation calls
Figura SHALL register load_image with authorized source_kind and opaque source_id, preserve Session ownership checks and existing business fields source kind, ID, display name and dimensions, and return one original image attachment through the unified tool-result contract. The first ordinary request SHALL contain source identities and names but no image bytes. The next ordinary request following a complete visual batch SHALL include each successful call's ordered saved attachments in that call's own native tool-result content. Different calls naming the same source SHALL each retain their logical image occurrence; storage deduplication SHALL NOT alter call association.

Successful extract_text and measure_chart calls SHALL provide saved OCR/measurement annotation attachments rather than request-time transient overlays. Successful rendering and explicit historical image reads SHALL use the same attachment-driven projection. Image bytes SHALL remain outside durable JSON, resource catalogs and public events. Requests after nonvisual batches SHALL NOT automatically resend images from earlier batches or Runs. No normal user message SHALL be fabricated solely to carry tool image feedback.

#### Scenario: Start a Run with multiple images
- **WHEN** a Run references multiple images and the checkpoint points to its initial model action
- **THEN** the model receives a text inventory of available image references and names, but no attachment image bytes

#### Scenario: Load multiple images in one tool batch
- **WHEN** successful `load_image` calls reference multiple authorized images in one fully committed batch
- **THEN** the next Provider request contains each call's original attachment and identity inside that call's tool result in call order, including separate occurrences when calls share a source

#### Scenario: Load an image from an earlier Run
- **WHEN** `load_image` names an authorized image resource from an earlier terminal Run in the same Session
- **THEN** Figura provides its bytes to the next Provider request without resending it in later requests

#### Scenario: Return annotated images after a measurement batch
- **WHEN** the immediately preceding fully committed batch contains one or more successful `measure_chart` calls
- **THEN** the next Provider request contains the matching JSON observations and one annotated image per call, identified by tool name and call ID

#### Scenario: Return OCR annotations after an OCR batch
- **WHEN** the immediately preceding fully committed batch contains successful `extract_text` calls
- **THEN** the next Provider request contains the matching OCR observations and one saved annotated image inside each call's tool result

#### Scenario: Do not repeat old overlays
- **WHEN** the immediately preceding batch contains no annotation attachment, including through an explicit historical image read
- **THEN** no annotation from an earlier batch or Run is attached

#### Scenario: Reject an image outside the resource catalog
- **WHEN** a call requests an unknown, unreferenced, or cross-Session source
- **THEN** Figura returns a bounded failure and provides no image bytes

#### Scenario: Fail before Provider dispatch if an observation image is unavailable
- **WHEN** a committed successful OCR or measurement result has a saved annotation that cannot be resolved or does not match its descriptor
- **THEN** request preparation fails before claiming a Provider attempt and sends no request

#### Scenario: Enforce Provider image bounds
- **WHEN** original and annotated images exceed a Provider image count, per-image size, aggregate size, or other request bound
- **THEN** request preparation fails before Provider dispatch

#### Scenario: Read an image after its source file disappears
- **WHEN** a `load_image` result committed but its source bytes cannot be resolved for the next request
- **THEN** request preparation fails and sends no image

#### Scenario: Keep duplicate source reads tied to separate calls
- **WHEN** two successful load_image calls in the same batch name the same Attachment
- **THEN** both results carry their original attachment with matching call IDs, while the underlying resource and file are reused
