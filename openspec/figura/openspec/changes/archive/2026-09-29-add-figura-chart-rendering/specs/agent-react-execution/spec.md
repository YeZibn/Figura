## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include a text inventory of every available attachment and committed Panel in the target Run's `RunExecutionState`, including same-Session attachments referenced only by earlier terminal Runs, plus accepted Figure and committed chart-render summaries. Historical render summaries SHALL remain textual; Figura SHALL NOT automatically resend image bytes from an earlier Run or earlier tool batch. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. Only original image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended as original images, in tool-call order. A fully committed batch containing successful `extract_text`, Cartesian measurement, or pie measurement calls SHALL additionally contribute one reconstructed annotated image per successful call, paired with its JSON tool observation and identified by tool name and call ID. A fully committed batch containing successful `render_chart_figure` calls SHALL additionally contribute each corresponding stored PNG once, paired with its committed JSON tool observation and identified by tool name and call ID, in tool-call order. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved calls or incomplete batches SHALL fail closed. Provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the fixed v1 instruction, persisted user text, and a complete textual image inventory, but no image bytes

#### Scenario: Include earlier Session Runs and their attachments
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments
- **THEN** the request contains all earlier Run messages in ascending Run ordinal, preserves their text and attachment IDs, lists their images in the available-image inventory, and does not attach historical image bytes

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the ordered assistant/tool interaction and attaches each loaded original image once after the text inventory in persisted tool-call order

#### Scenario: Include visual feedback for the latest observation batch
- **WHEN** the immediately preceding fully committed tool batch contains successful `extract_text`, Cartesian measurement, or pie measurement calls
- **THEN** the request contains each corresponding JSON tool result and one matching transient annotated image per successful call in tool-call order, with the tool name and call ID identified

#### Scenario: Include a rendered Figure in the next model action
- **WHEN** the immediately preceding fully committed tool batch contains one or more successful `render_chart_figure` calls
- **THEN** the next Provider request contains each corresponding JSON tool result and one matching stored PNG per successful render call in tool-call order, with the tool name and call ID identified

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch contains neither a successful `load_image`, `render_chart_figure`, `extract_text`, nor chart-measurement call
- **THEN** the request contains no image bytes from earlier batches or Runs

#### Scenario: Preserve completed prior-version calls as inert history
- **WHEN** an earlier Run or a completed interaction in the current Run contains a fully paired assistant tool call and result recorded under a prior registry version
- **THEN** Figura projects that interaction in its original order as conversation history and does not invoke its handler

#### Scenario: Fail closed on a prior-version unresolved tool call
- **WHEN** a tool call from a prior registry version has no committed matching result or belongs to an incomplete batch
- **THEN** Figura does not construct or dispatch a Provider request and does not execute the old call under the current registry

#### Scenario: Do not carry continuation across Runs
- **WHEN** an earlier Run's response has provider-private continuation data
- **THEN** Figura includes the normalized assistant response and committed tool facts in Session history but omits that continuation from the later Run's Provider request

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable Provider attempt is claimed, Figura SHALL derive authorized Attachment and Panel inventories from the target Run's `RunExecutionState`, resolve successful `load_image` results in the immediately preceding fully committed tool batch, reconstruct annotated images for successful `extract_text` and chart-measurement results in that batch from their authorized source and committed JSON, and resolve and validate the stored PNG for each successful `render_chart_figure` call in that batch against its committed render metadata. Figura SHALL validate image count, individual byte size, aggregate image byte size, and all other Provider limits. When the checkpoint follows no successful image-load, text-extraction, chart-measurement, or Figure-render call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested original, annotated, or rendered image cannot be resolved, does not belong to the Session inventory, fails integrity checks, or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every distinct image loaded by the immediately preceding batch resolves from the authorized same-Session inventory and the assembled request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those original image bytes held only in memory

#### Scenario: Assemble a valid request after text extraction or measurement
- **WHEN** each successful text-extraction or chart-measurement result in the immediately preceding batch has a matching committed result and its authorized source image can be resolved for annotation
- **THEN** Figura assembles and validates the matching annotated images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a valid request after Figure rendering
- **WHEN** each successful render call in the immediately preceding batch has a matching committed `chart_renders` observation and its private PNG matches the committed metadata
- **THEN** Figura assembles and validates the rendered images and may claim and dispatch the Provider request within Provider limits

#### Scenario: Assemble a request without a preceding image observation
- **WHEN** the current checkpoint follows Run creation or a tool batch without a successful `load_image`, `extract_text`, chart-measurement, or `render_chart_figure` result
- **THEN** Figura assembles and validates the text and tool history without resolving Attachment, Panel, or render image bytes

#### Scenario: An image required for visual feedback cannot be resolved
- **WHEN** a successful `load_image`, text-extraction, chart-measurement, or chart-render result refers to missing, unreadable, invalid, differently owned, or integrity-mismatched content needed by the next request
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request

#### Scenario: Images exceed Provider bounds
- **WHEN** original, annotated, and rendered images for the immediately preceding tool batch exceed Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt
