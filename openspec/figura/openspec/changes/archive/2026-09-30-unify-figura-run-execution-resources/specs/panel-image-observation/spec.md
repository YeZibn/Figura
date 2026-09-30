## REMOVED Requirements

### Requirement: RunExecutionState is reconstructed from Session-owned image facts
**Reason**: Its six separate top-level collections are replaced by the unified typed resource catalog defined by `run-execution-resources`; the old inventory and result projections are no longer independently addressable interfaces.
**Migration**: Agent, tool, request, and Gateway consumers query the new target Run resource catalog by kind and typed reference. Existing attachment, Panel, observation, Figure, and render records are reconstructed from their current authoritative Run and Sources facts without a data migration.

## MODIFIED Requirements

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
