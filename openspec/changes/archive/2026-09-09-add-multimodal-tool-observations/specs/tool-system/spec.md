## MODIFIED Requirements

### Requirement: Structured result and serialization

The system SHALL normalize tool execution into structured data, zero or more
generated image payloads with captions, and zero or more non-fatal warnings.
The structured portion SHALL serialize as a JSON string fit to enter message
history, while generated images remain separate from JSON serialization. Tools
that return existing JSON-serializable values SHALL continue to produce the
same structured observation with no images or warnings. A failed call SHALL be
represented as a structured error object so the LLM or an external host can
read success and failure through the same observation contract.

#### Scenario: Legacy successful result remains JSON-compatible

- **WHEN** an existing tool succeeds and returns a JSON-serializable value
- **THEN** that value is returned as the structured JSON observation with no
  generated images, preserving its current model-visible behavior

#### Scenario: Enriched result separates data from images

- **WHEN** a tool succeeds and returns structured data plus generated images
- **THEN** the structured data and image metadata are JSON-serializable while
  the image payloads are exposed separately for multimodal transport

#### Scenario: Failure becomes a structured error

- **WHEN** a tool call raises, its structured data cannot be serialized, or its
  enriched result is malformed
- **THEN** the structured observation contains an `{"error": ...}` object
  rather than propagating an exception or un-serializable value

#### Scenario: Invalid image does not invalidate structured data

- **WHEN** a tool returns serializable structured data alongside an invalid
  generated image
- **THEN** the structured observation remains successful and reports the image
  problem as a non-fatal warning
