## MODIFIED Requirements

### Requirement: Persist render artifacts privately and replay local writes idempotently
Figura SHALL store each rendered PNG in private managed storage, outside tool-result JSON and public Run records. The artifact identity SHALL be the rendering tool call's `(run_id, call_id)` pair; its managed filename SHALL be derived safely from that identity and SHALL NOT be model-controlled. The PNG SHALL pass image-format, positive-dimension, and existing Figura image-size checks before success is committed. `render_chart_figure` SHALL use the existing `idempotent_local_write` replay contract: replay of the same Run/call SHALL return the original artifact and metadata rather than create a second artifact. Installation SHALL be atomic or staged so interruption before ToolResultFact commit cannot expose an uncommitted render. Missing, corrupted, or digest-mismatched content SHALL fail closed; Figura SHALL NOT silently replace it with another image.

Every new successful render result SHALL include one rendered attachment whose typed resource reference is chart_render plus the originating Run/call, and whose media type, byte count, dimensions and digest agree with the business result. The image SHALL enter the next ordinary model action inside the render call's own tool-result content. Media normalization SHALL preserve the existing canonical stored PNG on idempotent replay, not install a different image for the same rendered artifact.

#### Scenario: Keep image bytes out of durable tool facts
- **WHEN** a render result commits
- **THEN** the result fact contains bounded render metadata and a matching rendered attachment description while PNG bytes remain in private managed storage

#### Scenario: Replay a render after an uncertain local write
- **WHEN** recovery replays the same render Run/call after the image was installed but before its result committed
- **THEN** the handler returns the existing validated artifact and does not create a duplicate

#### Scenario: Keep an uncommitted artifact out of projections
- **WHEN** an image file exists without a committed successful tool result
- **THEN** Agent state and Web projections do not expose it as a completed render

#### Scenario: Reject corrupted or missing stored content
- **WHEN** a committed render references an image that is missing, invalid, or does not match its recorded SHA-256
- **THEN** Figura returns a bounded storage or integrity failure and does not substitute another artifact

### Requirement: Project committed render outcomes into RunExecutionState
Figura SHALL expose each committed render_chart_figure outcome in the target Run's read-only RunExecutionState.resources catalog as a typed chart_render resource, following the shared run-execution-resources contract. Its typed reference SHALL identify the originating run_id and call_id; its content SHALL retain attempt_id, the nullable typed Figure reference, and the committed outcome. A successful render resource SHALL be included only when its Figure reference resolves to an accepted Figure in the same Session and authorized Run prefix, and SHALL contain exactly one bounded result with figure_digest, image_sha256, media_type, byte_count, width, and height. A failed render resource SHALL retain exactly one structured error and any syntactically valid Figure reference; otherwise its Figure reference SHALL be null. Resources SHALL follow the catalog's deterministic order, exclude attempts without committed results and facts from another Session, and SHALL NOT create a second durable copy of render outcomes.

A successful resource SHALL retain the result's ordered attachment descriptions and expose the same ChartRender identity to Prompt indexing, history reads and image reads. An explicitly migrated success without recoverable media SHALL keep its original business metadata but SHALL advertise no image availability; reads SHALL fail safely rather than regenerate. Failed resources SHALL have no successful attachment. No second render identity or result store SHALL be created.

#### Scenario: Include a committed successful render
- **WHEN** a render call references an accepted same-Session Figure in the authorized prefix and commits a successful result
- **THEN** the resource catalog contains its typed reference, Figure reference, successful outcome, and complete bounded render metadata

#### Scenario: Include a committed render failure
- **WHEN** a render call commits a structured failure, including when its syntactically valid Figure reference is not accepted or resolvable
- **THEN** the resource catalog contains its typed reference, failed outcome, and structured error without successful image metadata

#### Scenario: Omit incomplete and unauthorized render calls
- **WHEN** a render call has no committed result, or its facts belong to another Session or fall outside the target Run's authorized prefix
- **THEN** the target Run's resource catalog contains no render resource for that call

#### Scenario: Read a render again without creating a new resource
- **WHEN** a later Run explicitly reloads a committed ChartRender
- **THEN** the current read call returns the original rendered attachment reference and bytes without adding a second ChartRender resource
