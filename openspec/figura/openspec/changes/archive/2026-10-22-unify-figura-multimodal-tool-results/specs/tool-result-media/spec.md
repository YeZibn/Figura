## Purpose

Defines a single provider-neutral contract for images belonging to Figura tool results, including stable resource identity, immutable private media, publication and recovery integrity, and an explicit one-time cutover without online legacy result adapters.

## ADDED Requirements

### Requirement: Image attachments belong to one canonical tool result
Every normalized tool result SHALL include an ordered attachments array together with its exact call identity and mutually exclusive business result/error. Each successful image attachment SHALL contain resource_ref, image_kind, media_type, positive width and height, byte_count, sha256, and provenance. Raw image bytes, local paths, arbitrary image URLs, Provider messages and generated hints SHALL NOT be persisted in the result envelope. Failed results SHALL have no image attachments. Handler-produced media SHALL be normalized under the same contract for every tool rather than discovered later from the tool name.

#### Scenario: Return business data and an image as one observation
- **WHEN** a visual tool produces valid business data and a validated image
- **THEN** one call-associated result contains the original data and its ordered image descriptor, and the next selected model observation can include both in that call's native tool result

#### Scenario: Reject incompatible image metadata
- **WHEN** an attachment has mismatched type, dimensions, byte count, digest or source identity
- **THEN** the result is rejected or fails through the existing unknown-effect boundary and no inconsistent success is published

#### Scenario: Return a nonvisual tool result
- **WHEN** a successful tool returns no images
- **THEN** the canonical result still has attachments=[] and no alternate legacy return shape is accepted

### Requirement: Media identity reuses typed resource references
An attachment resource_ref SHALL reuse attachment/panel kind plus id or ocr/measurement/chart_render kind plus originating run_id and call_id. image_kind SHALL be exactly original, ocr_annotation, measurement_annotation, or rendered and SHALL agree with the resource kind. A ChartFigure SHALL NOT itself be treated as image media. A new producing call SHALL reference its own authorized logical resource; a reading call SHALL retain the original resource identity while using its own current tool_call_id. Reading an image SHALL NOT allocate another original resource ID or infer authorization from knowledge of an opaque ID or digest.

#### Scenario: Reload an image from a previous Run
- **WHEN** a current call loads a prior committed measurement image
- **THEN** its result uses the current read call ID and the attachment uses the originating measurement reference without creating another measurement resource

#### Scenario: Reject a future or cross-Session image
- **WHEN** a reference names another Session or work beyond the target Run's authorized prefix
- **THEN** Figura rejects it before returning media even if a matching file exists on disk

### Requirement: Successful visual outputs have durable matching media
New successful image-reading, OCR, measurement and rendering calls SHALL have their promised image prepared and verified before success publication. Sources SHALL keep media in private immutable storage; original/Panel/render content SHALL reuse existing resource identity and annotation media SHALL remain recoverable as recorded PNG bytes. Descriptor fingerprints SHALL match the exact published bytes. Later normal reads, Gateway image reads, retries and request construction SHALL NOT redraw annotations, rerun tools, repair missing media or substitute another image.

#### Scenario: Read recorded annotation bytes after restart
- **WHEN** a successful observation and its saved annotation survive restart
- **THEN** authorized consumers receive the recorded bytes verified by the committed descriptor without invoking an overlay renderer

#### Scenario: Fail a promised image before tool success
- **WHEN** image generation or installation fails with business effects known
- **THEN** the tool returns a bounded failure with no attachment rather than an image-less success

#### Scenario: Reject a missing committed image without repair
- **WHEN** an authorized committed image file is missing or fingerprint-mismatched
- **THEN** consumers report a bounded unavailable or integrity failure and do not silently regenerate it

### Requirement: Media installation and result publication preserve crash safety
Files SHALL be installed idempotently before result publication, and the result, attachment descriptions and checkpoint advancement SHALL commit atomically in the existing result transaction. Candidate files without committed result references SHALL NOT become Agent or Web resources. Eligible replay SHALL NOT associate recomputed data with a different uncommitted image merely because the logical call ID matches. Cleanup SHALL NOT race an active writer and SHALL occur only under an ownership-safe maintenance boundary. Existing declared business replay-effect and unknown-outcome rules SHALL remain authoritative.

#### Scenario: Interrupt after file installation
- **WHEN** execution stops after media installation but before the result transaction commits
- **THEN** no image result is exposed, the checkpoint remains unresolved, and eligible recovery can publish only a coherent data-and-image result

#### Scenario: Read after a committed result
- **WHEN** the result transaction already committed before interruption
- **THEN** recovery reuses the exact result and media descriptors without duplicate publication or handler execution

#### Scenario: Preserve in-flight media during cleanup
- **WHEN** a writer may still own an uncommitted image
- **THEN** cleanup does not delete that candidate and waits for the ownership-safe maintenance boundary

### Requirement: Media is removed with its owning Session
Saved observation media SHALL participate in the owning Session's existing private file staging, rollback restoration, committed deletion and startup reconciliation. Another Session's media SHALL remain unaffected, including equal-content images owned separately. Media paths, raw bytes, unrestricted descriptors and request hints SHALL NOT appear in public JSON, SSE or ordinary logs.

#### Scenario: Restore images after deletion rollback
- **WHEN** Session deletion rolls back after its private media is staged
- **THEN** the staged media is restored and existing authorized image reads continue to resolve the same content

#### Scenario: Finish cleanup after committed deletion
- **WHEN** deletion commits and the process stops before private staged files are removed
- **THEN** startup removes the inaccessible staged media and does not restore deleted resources

### Requirement: Cutover uses one-time migration rather than online adaptation
The result contract SHALL activate through one backed-up maintenance migration after prior Registry Runs are terminal, execution owners are inactive and compaction operations are closed. Migration SHALL preserve original call/attempt IDs, source identity, argument strings, business result/error values, statuses, event order and Provider-request audit records. It SHALL convert only outer media representation and materialize verified available images without executing historical OCR, measurement, decomposition, assembly, rendering or Provider calls.

Descriptors SHALL use provenance=recorded for verifiable retained media and migration_reconstructed for annotations materialized from supported historical source data during migration. Missing or unsupported historical media SHALL remain absent with an empty attachment collection and a private migration audit reason; original business facts SHALL remain readable. Every converted record SHALL use the same canonical online schema, without per-read old-format inference, old/new handler unions, hidden image backfill or a plain-user feedback fallback. A migration failure SHALL preserve the prior database state and recoverable files; rollback SHALL restore paired database and Sources backups.

#### Scenario: Refuse migration while work is active
- **WHEN** a Run, execution owner or compaction operation still requires the old active contract
- **THEN** migration refuses activation without automatically terminating that work or changing its frozen request

#### Scenario: Label a historical annotation reconstructed during migration
- **WHEN** the original annotation PNG was not retained but supported committed observation data and its authorized source can reconstruct one during maintenance
- **THEN** the migrated descriptor records migration_reconstructed and consumers do not claim that image is the exact original historical feedback

#### Scenario: Preserve text when old image data is unavailable
- **WHEN** migration cannot verify or materialize a historical image
- **THEN** original business data remains readable with attachments=[], the unavailable image is recorded in the private migration audit and online reads do not infer a replacement

#### Scenario: Activate only the canonical pipeline
- **WHEN** migration and coordinated Registry activation complete
- **THEN** all handlers, facts and projections use the canonical contract and neither the dictionary-return adapter nor the plain-user image append path exists
