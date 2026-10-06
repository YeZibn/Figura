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
Figura SHALL provide a common image-read operation for a typed resource reference. It SHALL resolve an Attachment or Panel only through the owning Session and the target Run's authorized resource catalog. For an OCR or measurement resource with a successful outcome, it SHALL reconstruct the existing transient annotation from its authorized source image and complete committed result. For a ChartRender resource with a successful outcome, it SHALL read its private PNG and verify its bytes, digest, media type, size, and dimensions against committed render metadata. A ChartFigure resource SHALL report that rendering is required and SHALL NOT implicitly run the render tool. Failed or otherwise nonvisual resources SHALL return a bounded not-readable result. No image bytes or annotation image SHALL be persisted into the catalog or tool-result JSON.

#### Scenario: Read an Attachment or Panel resource image
- **WHEN** an Agent tool or request consumer requests an authorized Attachment or Panel resource reference
- **THEN** Figura returns the validated image bytes for that Session resource only

#### Scenario: Read a successful observation as a transient annotated image
- **WHEN** a successful OCR or measurement resource and its authorized source image are available
- **THEN** Figura generates its matching annotation in memory and returns it without adding image bytes to durable results

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

### Requirement: Resource content follows the new chart contracts
The resource catalog SHALL expose Attachment, Panel, OCR, measurement, ChartFigure, and ChartRender content through the existing typed references. Attachment content SHALL preserve its owning Session, display filename, media type, byte count, and creation time; Panel content SHALL preserve its owning Session, originating Run, source Attachment, display name, and normalized polygon points. OCR content SHALL preserve attempt, typed source reference, optional scope, outcome, and exactly one complete bounded result or structured error.

Each new measurement resource SHALL originate from `measure_chart` v2 and contain attempt ID, tool name `measure_chart`, nullable authorized source reference, nullable scope, outcome, and exactly one complete v2 result or structured error. Its result SHALL preserve the common envelope and complete typed family observations; successful scope values SHALL remain unchanged and a null scope SHALL mean the complete selected image. The projection SHALL NOT recompute, normalize, or repair a committed result.

Each new accepted ChartFigure resource SHALL contain attempt ID, outcome, complete ChartFigure v2, and verified digest. It SHALL preserve ordered chart IDs, all ChartSpec v2 content, layout, and measurement references. Failed assembly SHALL retain its structured error without a successful Figure result. Each ChartRender resource SHALL preserve attempt, typed Figure reference, outcome, and exactly one bounded render result or structured error; successful metadata SHALL contain Figure digest, PNG SHA-256, media type, byte count, width, and height, while PNG bytes remain in private Sources storage.

The new typed chart-resource projection SHALL NOT parse, convert, or backfill ChartSpec/Figure v1 or results from `measure_bars`, `measure_lines`, `measure_scatter`, or `measure_pie`. Such facts SHALL remain unchanged in durable Run history and SHALL be omitted from the new typed chart-resource catalog. Their presence SHALL NOT prevent reconstruction of other valid resources. A malformed successful v2 fact or an identity/source mismatch SHALL fail resource construction rather than expose a repaired result.

#### Scenario: Preserve current source and Panel details
- **WHEN** an authorized Attachment and committed Panel are projected
- **THEN** their typed contents retain current Sources metadata and Panel geometry without image bytes or duplicate resource IDs

#### Scenario: Preserve v2 measurement results and scopes
- **WHEN** a `measure_chart` call has committed a successful or failed outcome
- **THEN** its resource retains the attempt, source reference, scope semantics, complete v2 result or safe error

#### Scenario: Preserve a complete ChartFigure v2
- **WHEN** a Figure v2 assembly result commits with a digest matching the complete Figure
- **THEN** its resource exposes the full Figure v2, every child ChartSpec v2, layout, and measurement references

#### Scenario: Keep old chart facts outside the typed catalog
- **WHEN** the authorized Run prefix contains a v1 Figure or a result from a removed standalone measurement tool
- **THEN** the new chart-resource projection does not parse, convert, or expose that fact as a v2 resource, and still reconstructs unrelated valid resources

#### Scenario: Keep image bytes outside resources
- **WHEN** resource content is listed, looked up, serialized into prompt context, or returned through a tool result
- **THEN** it contains no image bytes, local path, credential, or raw exception detail

#### Scenario: Reject an inconsistent v2 success
- **WHEN** a successful v2 measurement, Figure, or render fact has mismatched identity, source, or content digest
- **THEN** resource construction fails closed and exposes no repaired success

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
