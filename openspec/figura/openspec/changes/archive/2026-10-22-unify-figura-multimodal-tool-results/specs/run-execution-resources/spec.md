## MODIFIED Requirements

### Requirement: Resource lookup provides one authorized image-read path
Figura SHALL provide one image-read operation using a complete typed reference in the target Run's full authorized resource catalog. Attachment and Panel reads SHALL verify owning Session and source metadata. Successful OCR and measurement reads SHALL locate an already materialized annotation through the committed attachment description; they SHALL NOT reconstruct overlays on read. Successful ChartRender reads SHALL resolve the existing private PNG and verify its committed attachment and business metadata. Every read SHALL verify media type, byte count, positive dimensions and SHA-256 where supplied by the committed descriptor.

ChartFigure reads SHALL report that explicit rendering is required and SHALL NOT invoke a renderer implicitly. Failed, unresolved, nonvisual, migrated-without-media, missing, corrupted or unauthorized resources SHALL return a bounded not-readable result without substituting a newly generated image. The catalog and tool-result JSON SHALL contain descriptors, never pixels or local paths.

#### Scenario: Read an Attachment or Panel resource image
- **WHEN** an Agent tool or request consumer requests an authorized Attachment or Panel resource reference
- **THEN** Figura returns the validated image bytes for that Session resource only

#### Scenario: Read a successful observation as its recorded annotated image
- **WHEN** a successful OCR or measurement resource has an authorized committed attachment and its matching recorded file
- **THEN** Figura reads the saved annotation, validates its descriptor and returns the same bytes without redrawing

#### Scenario: Read a successful rendered image
- **WHEN** a successful ChartRender resource references a valid private PNG matching its committed metadata
- **THEN** Figura returns that PNG after all integrity and Provider bounds checks pass

#### Scenario: Require explicit rendering for a Figure
- **WHEN** a consumer requests image bytes for an accepted ChartFigure that has no successful render resource
- **THEN** Figura reports that an explicit render operation is required and does not render implicitly

#### Scenario: Reject unauthorized or missing image content
- **WHEN** a resource image reference is cross-Session, outside the Run catalog, missing, unreadable, corrupted, or inconsistent with committed metadata
- **THEN** Figura returns a bounded failure and provides no replacement or unauthorized image bytes

#### Scenario: Keep failed observations out of visual feedback
- **WHEN** the latest complete tool batch contains a failed OCR, measurement, or render resource
- **THEN** its structured error remains available by reference and the image-read operation returns no image

#### Scenario: Do not repair a missing annotation on read
- **WHEN** an OCR or measurement record remains valid but its saved annotation is missing or fails the committed digest
- **THEN** the image reader reports unavailability without running OCR, measurement, overlay rendering or a replacement write

### Requirement: Resource content follows the new chart contracts
The resource catalog SHALL expose Attachment, Panel, OCR, measurement, ChartFigure, and ChartRender content through the existing typed references. Attachment content SHALL preserve its owning Session, display filename, media type, byte count, and creation time; Panel content SHALL preserve its owning Session, originating Run, source Attachment, display name, and normalized polygon points. OCR content SHALL preserve attempt, typed source reference, optional scope, outcome, and exactly one complete bounded result or structured error.

Each new measurement resource SHALL originate from `measure_chart` with the current version 3 result and contain attempt ID, tool name `measure_chart`, nullable authorized source reference, nullable scope, outcome, and exactly one complete version 3 measurement result or structured error. Its result SHALL preserve the common envelope and complete typed family observations; successful scope values SHALL remain unchanged and a null scope SHALL mean the complete selected image. The projection SHALL NOT recompute, normalize, or repair a committed result.

Each new accepted ChartFigure resource SHALL contain attempt ID, outcome, complete ChartFigure v2, and verified digest. It SHALL preserve ordered chart IDs, all ChartSpec v2 content, layout, and measurement references. Failed assembly SHALL retain its structured error without a successful Figure result. Each ChartRender resource SHALL preserve attempt, typed Figure reference, outcome, and exactly one bounded render result or structured error; successful metadata SHALL contain Figure digest, PNG SHA-256, media type, byte count, width, and height, while PNG bytes remain in private Sources storage.

The new typed chart-resource projection SHALL NOT parse, convert, or backfill ChartSpec/Figure v1 or results from `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie`. Their original business payloads and identities SHALL remain unchanged in durable Run history and SHALL be omitted from the new typed chart-resource catalog. Their presence SHALL NOT prevent reconstruction of other valid resources. A malformed successful supported fact or an identity/source mismatch SHALL fail resource construction rather than expose a repaired result.

OCR, measurement and ChartRender contents SHALL additionally retain their complete committed ordered attachment descriptions. Business data SHALL remain canonical and SHALL NOT be converted, recomputed or inferred from media. Only the explicit maintenance migration may enrich an outer result envelope while preserving its original business payload and identity; normal resource construction SHALL NOT backfill attachments. A migrated result without usable media SHALL remain text-readable but SHALL NOT advertise image availability. New image-enabled results SHALL advertise their actual image_kind and resource reference without creating a new ID on reload.

#### Scenario: Preserve current source and Panel details
- **WHEN** an authorized Attachment and committed Panel are projected
- **THEN** their typed contents retain current Sources metadata and Panel geometry without image bytes or duplicate resource IDs

#### Scenario: Preserve current measurement results and scopes
- **WHEN** a `measure_chart` call has committed a successful or failed outcome
- **THEN** its resource retains the attempt, source reference, scope semantics, complete version 3 measurement result or safe error

#### Scenario: Preserve a complete ChartFigure v2
- **WHEN** a Figure v2 assembly result commits with a digest matching the complete Figure
- **THEN** its resource exposes the full Figure v2, every child ChartSpec v2, layout, and measurement references

#### Scenario: Keep old chart facts outside the typed catalog
- **WHEN** the authorized Run prefix contains a v1 Figure or a result from a removed standalone measurement tool
- **THEN** the new chart-resource projection does not parse, convert, or expose that fact as a current typed chart resource, and still reconstructs unrelated valid resources

#### Scenario: Keep image bytes outside resources
- **WHEN** resource content is listed, looked up, serialized into prompt context, or returned through a tool result
- **THEN** it contains no image bytes, local path, credential, or raw exception detail

#### Scenario: Reject an inconsistent supported success
- **WHEN** a successful supported measurement, Figure, or render fact has mismatched identity, source, or content digest
- **THEN** resource construction fails closed and exposes no repaired success

#### Scenario: Reuse the same image identity through result and catalog
- **WHEN** a tool result is committed with an image attachment and is later projected into the catalog
- **THEN** its resource entry exposes the same full reference and descriptor while image bytes remain only in private storage
