## Purpose

Provides Agent and tool consumers one typed, same-Session resource view of the target Run's available images and committed OCR, measurement, chart-canvas, and rendered-image content.

## ADDED Requirements

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

### Requirement: Resource content preserves the complete current facts
The catalog SHALL expose Attachment and Panel content from their current Sources owners. Attachment content SHALL contain `session_id`, display `filename`, `media_type`, `byte_count`, and `created_at`; its opaque Attachment ID SHALL be in the resource reference. Panel content SHALL contain `session_id`, its originating `run_id`, `source_attachment_id`, display `name`, and complete normalized `points`; its opaque Panel ID SHALL be in the reference.

Each OCR resource SHALL contain `attempt_id`, nullable typed `source_ref`, nullable `observation_scope`, `outcome`, and exactly one of its complete existing bounded OCR `result` or structured `error`. Each measurement resource SHALL contain `attempt_id`, `tool_name`, nullable typed `source_ref`, nullable `observation_scope`, `outcome`, and exactly one of its complete existing bounded measurement `result` or structured `error`. OCR `result` SHALL preserve `source_kind`, `source_id`, `image_size.width`, `image_size.height`, `coordinate_system`, `available`, `truncated`, and every bounded snippet's `snippet_id`, `text`, `bbox_px`, and `confidence`. Measurement `result` SHALL preserve the complete result contract of its named measurement tool. The originating `run_id` and `call_id` SHALL be represented by the resource reference, not duplicated in content.

A successful ChartFigure resource SHALL contain `attempt_id`, `outcome`, and a result containing both the complete accepted `ChartFigure` and its verified `figure_digest`. The complete value SHALL retain its existing `schema_version`, `title`, `layout.columns`, ordered chart IDs, complete child `ChartSpecData`, and measurement references. A failed Figure assembly SHALL contain its attempt, failed outcome, and structured error without a successful Figure result. A ChartRender resource SHALL contain `attempt_id`, nullable typed `figure_ref`, `outcome`, and exactly one of its existing bounded render metadata result or structured error. Successful render metadata SHALL contain `figure_digest`, `image_sha256`, `media_type`, `byte_count`, `width`, and `height`; PNG bytes SHALL remain in private Sources storage.

Successful OCR and measurement observations SHALL retain their requested scope. A successful call omitting a scope SHALL have a null scope representing the complete selected image. A supplied scope SHALL preserve the existing `include`/`exclude` polygon contract and immutable normalized values. Failed observations SHALL retain a structurally valid supplied scope; a missing or invalid failed-call scope SHALL be null and SHALL NOT claim full-image coverage. Projection SHALL not recompute an observation or alter its result. Successful results SHALL match the persisted call, attempt, source, and existing tool result contract. A result/attempt identity mismatch or malformed successful result SHALL fail state construction.

#### Scenario: Preserve complete attachment and Panel details
- **WHEN** a referenced Attachment and a committed Panel are projected into the catalog
- **THEN** their typed contents expose their full current Sources metadata and Panel geometry without storing image bytes or duplicating the resource ID

#### Scenario: Preserve OCR and measurement results and scopes
- **WHEN** authorized OCR and measurement calls have committed successful or failed outcomes
- **THEN** each appears as its own typed resource with the originating attempt, source reference, scope semantics, and complete result or structured error

#### Scenario: Preserve complete accepted Figure content
- **WHEN** a Figure assembly has committed a successful result whose digest matches the complete accepted Figure
- **THEN** the Figure resource makes the full ChartFigure, child ChartSpecData, layout, and measurement references available through its typed reference

#### Scenario: Preserve committed Figure and render failures
- **WHEN** a Figure assembly or render call has committed a structured failure
- **THEN** its tool reference resolves to its attempt, failed outcome, and error without appearing as a successful Figure or image

#### Scenario: Keep image bytes outside resource content
- **WHEN** a resource is listed, looked up, serialized into prompt context, or returned through an ordinary tool result
- **THEN** it contains no image bytes, local file path, API credential, or raw exception detail

#### Scenario: Reject inconsistent successful tool facts
- **WHEN** a committed successful OCR, measurement, Figure, or render observation has mismatched call/attempt/source identity or violates its current result contract
- **THEN** Figura fails resource construction and does not publish a partial or repaired successful resource

### Requirement: Every resource is reconstructed from the same authorized Run prefix
For a target Run, the resource catalog SHALL be reconstructed from earlier terminal Runs in the same Session in ascending contiguous ordinal order, followed by the supplied committed prefix of the target Run. The supplied `RunState` values and their tool facts SHALL be authoritative for results; a newer Session snapshot SHALL NOT substitute later current-Run facts or facts from a later Run. Sources metadata and files MAY be used to resolve and verify resources only when a matching eligible fact or Run input in that prefix authorizes them.

Every distinct Attachment referenced by those Run inputs SHALL appear once, in first-reference order. A Panel SHALL appear only when its creation result committed in the prefix and its Sources record matches that result. OCR, measurement, Figure, and render resources SHALL retain each committed logical call, ordered by Run ordinal, persisted tool-call sequence, call position, and result item order where applicable. Repeated observations of the same image SHALL remain distinct resources. A successful observation with an unresolved or unauthorized source SHALL fail closed; a failed observation SHALL remain queryable with its safe error and any syntactically valid source reference, but that reference SHALL NOT grant image access. Started attempts without committed outcomes SHALL NOT appear as completed resources. Session-wide Panel listings SHALL continue to include all committed same-Session Panels independently of a target Run's prefix.

#### Scenario: Carry resources forward to a later Run
- **WHEN** a Session's later Run follows a terminal Run containing referenced Attachments, committed Panels, observations, Figures, and renders
- **THEN** its catalog includes all eligible earlier resources and its own resources in deterministic Session/Run order

#### Scenario: Exclude later Run resources
- **WHEN** a Session snapshot contains resources from a Run later than the target Run
- **THEN** none of those later resources or their metadata enter the target Run's catalog

#### Scenario: Respect the supplied current Run prefix
- **WHEN** the latest Session snapshot contains newer tool facts than the supplied target RunState
- **THEN** the catalog reflects only the supplied prefix and does not expose those newer results early

#### Scenario: Exclude a Panel before its creation result commits
- **WHEN** a Panel file or record exists but its successful decomposition result is outside the supplied prefix
- **THEN** the Panel is absent from the catalog until that result is included

#### Scenario: Preserve multiple scans of one source
- **WHEN** a source is scanned or measured repeatedly, including across Runs
- **THEN** each committed call has its own reference and complete result in chronological order

#### Scenario: Preserve safe failures with an unknown source
- **WHEN** an OCR or measurement call fails and its source is malformed or unavailable
- **THEN** its failed tool resource remains queryable by its Run/call reference, but no image read is authorized through that source

#### Scenario: Reconstruct the same content after restart
- **WHEN** the same committed Session facts and Sources records are read after process restart
- **THEN** Figura reconstructs the same resource references, ordering, content, and outcomes without resource-table migration

#### Scenario: Keep Session-wide Panel listing behavior
- **WHEN** a Session-level Panel listing is requested for a Session with multiple Runs
- **THEN** it returns all committed same-Session Panels while each target Run catalog still respects its own prefix

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
