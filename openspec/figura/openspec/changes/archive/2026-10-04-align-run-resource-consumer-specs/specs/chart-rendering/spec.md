## MODIFIED Requirements

### Requirement: Project committed render outcomes into RunExecutionState
Figura SHALL expose each committed render_chart_figure outcome in the target Run's read-only RunExecutionState.resources catalog as a typed chart_render resource, following the shared run-execution-resources contract. Its typed reference SHALL identify the originating run_id and call_id; its content SHALL retain attempt_id, the nullable typed Figure reference, and the committed outcome. A successful render resource SHALL be included only when its Figure reference resolves to an accepted Figure in the same Session and authorized Run prefix, and SHALL contain exactly one bounded result with figure_digest, image_sha256, media_type, byte_count, width, and height. A failed render resource SHALL retain exactly one structured error and any syntactically valid Figure reference; otherwise its Figure reference SHALL be null. Resources SHALL follow the catalog's deterministic order, exclude attempts without committed results and facts from another Session, and SHALL NOT create a second durable copy of render outcomes.

#### Scenario: Include a committed successful render
- **WHEN** a render call references an accepted same-Session Figure in the authorized prefix and commits a successful result
- **THEN** the resource catalog contains its typed reference, Figure reference, successful outcome, and complete bounded render metadata

#### Scenario: Include a committed render failure
- **WHEN** a render call commits a structured failure, including when its syntactically valid Figure reference is not accepted or resolvable
- **THEN** the resource catalog contains its typed reference, failed outcome, and structured error without successful image metadata

#### Scenario: Omit incomplete and unauthorized render calls
- **WHEN** a render call has no committed result, or its facts belong to another Session or fall outside the target Run's authorized prefix
- **THEN** the target Run's resource catalog contains no render resource for that call
