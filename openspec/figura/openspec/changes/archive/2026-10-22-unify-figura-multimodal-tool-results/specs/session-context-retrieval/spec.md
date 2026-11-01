## MODIFIED Requirements

### Requirement: Read resolves a stable reference to its original content
Figura SHALL provide read-only resolution of conversation-message references and tool-result/resource references to complete original message data or committed typed business result/error with ordered attachment descriptions. Reads SHALL preserve Run, record/call identity, ordering, outcomes and media provenance. They SHALL NOT rerun tools, read image pixels implicitly, invent missing results, mutate the source Run or materialize new media.

Callers may request a field or range under the existing selector rules; absent a selector, the selected source item SHALL be returned completely subject to existing payload and Provider rules. Image references present in text or structured output SHALL NOT be treated as loaded images. Runtime audit facts and complete source references SHALL stay authoritative.

#### Scenario: Read an exact historical message
- **WHEN** the Agent reads a valid message reference from search results or a summary
- **THEN** Figura returns the original committed message content and its source identity

#### Scenario: Read a complete tool result
- **WHEN** the Agent reads a valid tool-resource reference
- **THEN** Figura returns the complete committed typed content or structured error associated with that exact Run and call

#### Scenario: Read an unresolved call
- **WHEN** a referenced historical call has no committed result and its outcome is unknown
- **THEN** Figura returns the source-linked unknown status and no fabricated observation

#### Scenario: Reject an unavailable reference
- **WHEN** the requested reference is malformed, outside the authorized prefix, or absent
- **THEN** Figura returns a bounded not-found or not-readable result without revealing another Session's content

#### Scenario: Read attachment metadata without loading image pixels
- **WHEN** read_history resolves a committed visual tool result or corresponding typed resource
- **THEN** the returned structured content includes ordered attachment references and provenance but no image bytes or per-image observation hints

### Requirement: Read authorized historical images through typed resource references
Figura SHALL let the Agent request visual content by authorized typed Attachment, Panel, successful OCR/measurement, or ChartRender references. Native input SHALL accept exactly those image resource kinds with their complete typed identities and SHALL exclude message, tool_result and chart_figure. Text and complete structured content SHALL remain available through read_history.

A successful image read SHALL return one attachment in the current read call's normal multimodal tool result, with the original resource_ref, image_kind and provenance unchanged. The current tool_call_id SHALL identify the read invocation rather than the originating producer. The read SHALL verify Session, authorized prefix, media metadata and content integrity. It SHALL NOT rerun OCR, measurement, decomposition, assembly or rendering, redraw a saved annotation, or create another resource identity. ChartFigure SHALL require explicit rendering; failed, unresolved, unavailable or corrupted media SHALL produce a bounded image-read failure and no attachment.

#### Scenario: Read a prior Attachment or Panel image
- **WHEN** the Agent requests an Attachment or Panel reference present in the authorized resource catalog
- **THEN** Figura validates the owning Session and returns the image to the next Provider request

#### Scenario: Read a prior observation or render image
- **WHEN** the Agent requests a successful OCR or measurement annotation, or a successful ChartRender reference
- **THEN** Figura reads the saved source or annotation, verifies its committed descriptor, and returns it as an attachment of the current read call

#### Scenario: Require an explicit render for a Figure
- **WHEN** the Agent submits a ChartFigure reference to the image reader instead of an accepted image resource reference
- **THEN** the native input contract rejects it and guidance directs the Agent to explicitly render the Figure or read an existing ChartRender reference without rendering implicitly

#### Scenario: Reject unauthorized, failed, or corrupt image content
- **WHEN** a reference is cross-Session, outside the authorized Run prefix, failed, missing, or inconsistent with committed metadata
- **THEN** Figura returns no image bytes and reports a bounded failure

#### Scenario: Reject a nonvisual history reference before image dispatch
- **WHEN** the Agent supplies a message or tool-result reference to the image tool
- **THEN** native argument validation rejects the reference before its image handler runs and the historical content reader remains available for that reference

#### Scenario: Keep source identity distinct from the loading call
- **WHEN** a call in Run B reads the image resource produced by a call in Run A
- **THEN** the tool result belongs to the current Run B call while its attachment resource_ref still names Run A's original resource and no duplicate resource is created
