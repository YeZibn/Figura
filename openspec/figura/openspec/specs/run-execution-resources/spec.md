# run-execution-resources Specification

## Purpose

Provides Agent and tool consumers one typed, same-Session resource view of the target Run's available images and committed OCR, measurement, chart-canvas, and rendered-image content.

## Requirements

### Requirement: A Run exposes resources through one typed catalog
Figura SHALL expose a read-only `RunExecutionState` with exactly `run_id` and `resources` as its top-level fields. Every resource SHALL have exactly one typed `ref` and one typed `content`; its kind SHALL be carried by its reference. The resource reference SHALL be one of: an image reference with `kind` (`attachment` or `panel`) and opaque `id`; or a tool-result reference with `kind` (`ocr`, `measurement`, `chart_figure`, or `chart_render`), originating `run_id`, and logical `call_id`. A tool-result reference SHALL remain unique when two Runs use the same `call_id`.

The catalog SHALL support ordered listing of all resources or a requested kind and lookup by the full typed reference. A lookup SHALL return the complete matching typed content or a bounded not-found result; it SHALL NOT return only a kind-specific summary in place of the resource content. Resource values SHALL be read-only. The catalog SHALL not add image bytes, local paths, or a second durable result store.

#### Scenario: List every resource from the target Run history
- **WHEN** a target Run has referenced Attachments, committed Panels, OCR, measurements, Figures, and render results in its authorized prefix
- **THEN** its execution state exposes all of them through one ordered `resources` collection, with each resource kind and stable reference available for lookup

#### Scenario: Distinguish tool references across Runs
- **WHEN** two Runs in one Session contain tool resources with the same `call_id`
- **THEN** their references remain distinct by `kind` and originating `run_id`

#### Scenario: Query a resource by its complete reference
- **WHEN** a consumer looks up an existing typed resource reference
- **THEN** it receives the complete typed content associated with that exact resource

#### Scenario: Reject an unknown resource reference
- **WHEN** a consumer looks up a reference that is absent from the target Run's resource catalog
- **THEN** Figura returns a bounded not-found result and reveals no content from another Session or Run prefix

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
### Requirement: Reconstruct supported resources from the authorized Run prefix
For a target Run, Figura SHALL reconstruct the catalog from earlier terminal Runs in the same Session in ascending contiguous ordinal order followed by the supplied committed prefix of the target Run. The supplied RunState values and their facts SHALL be authoritative; newer Session snapshots SHALL NOT contribute later facts. Sources metadata and files MAY be read only when an eligible Run input or committed fact in that prefix authorizes them.

Each distinct referenced Attachment SHALL appear once in first-reference order. A Panel SHALL appear only after its creation result commits in the prefix and its Sources record matches that result. OCR, `measure_chart` v2, ChartFigure v2, and ChartRender resources SHALL preserve each supported committed call in deterministic Run/sequence/position order. Repeated supported observations SHALL remain distinct. Legacy chart facts SHALL be skipped from typed chart-resource projection without conversion and without blocking unrelated resources. Successful supported observations with unresolved or unauthorized sources SHALL fail closed; failed observations SHALL remain queryable with safe errors but SHALL NOT grant image access. Started attempts without committed outcomes SHALL NOT appear as completed resources. Session-wide Panel listings SHALL continue to include all committed same-Session Panels independently of the target Run prefix.

#### Scenario: Carry supported resources to a later Run
- **WHEN** a later Run follows an earlier terminal Run with Attachments, committed Panels, OCR, v2 measurements, v2 Figures, or renders
- **THEN** the target catalog includes each eligible supported resource in deterministic order

#### Scenario: Exclude facts outside the target prefix
- **WHEN** a Session snapshot contains later Run facts or uncommitted current-Run results
- **THEN** none of them enter the target Run catalog

#### Scenario: Exclude a Panel before its creation commits
- **WHEN** a Panel image or record exists without an eligible committed creation result
- **THEN** the Panel is absent from the target catalog

#### Scenario: Preserve repeated v2 measurements
- **WHEN** the same source is measured more than once, including across Runs
- **THEN** every committed `measure_chart` call has its own reference and complete result

#### Scenario: Keep a failed observation from authorizing an image
- **WHEN** a supported observation fails with an unavailable or malformed source
- **THEN** its safe failure remains queryable but no image read is authorized through it

#### Scenario: Ignore legacy chart facts without blocking other resources
- **WHEN** the prefix contains v1 Figure or removed-tool facts alongside valid current resources
- **THEN** those legacy chart facts are not typed or converted and valid current resources are still reconstructed

#### Scenario: Reconstruct current resources after restart
- **WHEN** the same supported committed facts and Sources records are loaded after process restart
- **THEN** Figura reconstructs the same v2 chart references, contents, order, and outcomes without a resource-table migration

#### Scenario: Preserve Session-wide Panel listing
- **WHEN** a Session-level Panel listing is requested for a multi-Run Session
- **THEN** it returns all committed same-Session Panels while each Run catalog remains prefix-scoped

### Requirement: Prompt resource catalog provides compact, decision-useful summaries
The Agent SHALL project OCR and measurement resources into the Prompt catalog as compact summaries with their complete typed resource references. OCR summaries SHALL include source reference, scope kind, outcome, availability, truncation state, snippet count, and a bounded text preview. Measurement summaries SHALL include source reference, scope kind, outcome, chart type and status when available, committed structure status and detected counts, confidence, calibration counts, issue and warning counts, and bounded issue-code and warning previews. Failed resources SHALL expose their safe structured error without success-only fields. The projection SHALL NOT include the complete OCR snippets, measurement observations, evidence, calibrations, value provenance, image bytes, or local paths.

The summary SHALL be derived deterministically from the complete committed resource. Detected counts SHALL be copied from the committed measurement coverage rather than recomputed. Any preview omission or text shortening SHALL be marked separately from the source result's own truncation state. The Prompt SHALL direct the Agent to use the listed reference with `read_history` when exact text, coordinates, values, or evidence are needed. The full resource lookup and `RunExecutionState` SHALL continue to expose the complete committed content.

#### Scenario: Locate relevant OCR text from its summary
- **WHEN** a successful OCR resource contains text snippets
- **THEN** the Prompt catalog includes its typed reference, source, scope kind, availability, source truncation state, snippet count, and a bounded preview, with no full snippet coordinates or confidence values

#### Scenario: Preserve complete OCR content for explicit reading
- **WHEN** the Agent follows an OCR catalog reference with `read_history`
- **THEN** Figura returns the complete committed OCR content or the requested selector while the catalog itself remains compact

#### Scenario: Summarize measurement quality without changing evidence
- **WHEN** a successful measurement resource has coverage, confidence, calibrations, issues, warnings, and family observations
- **THEN** the Prompt catalog exposes the committed coverage counts and compact quality metadata without embedding the family observations, evidence, calibration parameters, or value provenance

#### Scenario: Distinguish preview omission from source truncation
- **WHEN** an OCR or measurement summary omits entries or shortens preview text
- **THEN** its summary preview state reports that omission separately and preserves the source result's original `truncated` value

#### Scenario: Keep failed resource summaries truthful
- **WHEN** an OCR or measurement call has a committed failure
- **THEN** the Prompt catalog exposes its typed reference, outcome, and safe structured error without manufacturing success metadata

#### Scenario: Rebuild the compact catalog from full resources
- **WHEN** a later Run reconstructs a supported resource from committed Runtime facts
- **THEN** the typed resource retains its complete content and the Prompt catalog derives the same bounded summary without adding a separate durable store
