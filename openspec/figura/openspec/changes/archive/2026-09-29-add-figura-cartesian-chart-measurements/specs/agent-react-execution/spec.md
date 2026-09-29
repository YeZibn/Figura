## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include a text inventory of every available attachment and committed Panel in the target Run's `RunExecutionState`, including same-Session attachments referenced only by earlier terminal Runs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. Only original image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended as original images, in tool-call order. A fully committed batch containing successful Cartesian measurement calls SHALL additionally contribute one reconstructed annotated image per successful call, paired with its JSON tool observation and identified by tool name and call ID. Completed tool-call/result pairs recorded under an earlier registry version SHALL be projected as inert conversation history and SHALL NOT be executed again; unresolved calls or incomplete batches SHALL fail closed. Provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the fixed v1 instruction, persisted user text, and a complete textual image inventory, but no image bytes

#### Scenario: Include earlier Session Runs and their attachments
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments
- **THEN** the request contains all earlier Run messages in ascending Run ordinal, preserves their text and attachment IDs, lists their images in the available-image inventory, and does not attach historical image bytes

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the ordered assistant/tool interaction and attaches each loaded original image once after the text inventory in persisted tool-call order

#### Scenario: Include visual feedback for the latest measurement batch
- **WHEN** the immediately preceding fully committed tool batch contains successful Cartesian measurement calls
- **THEN** the request contains each corresponding JSON tool result and a matching annotated image in tool-call order, with the measurement tool name and call ID identified

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch contains neither a successful `load_image` call nor a successful Cartesian measurement call
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
Before a durable Provider attempt is claimed, Figura SHALL derive authorized Attachment and Panel inventories from the target Run's `RunExecutionState`, resolve successful `load_image` results in the immediately preceding fully committed tool batch, reconstruct annotated images for successful Cartesian measurement results in that batch from their authorized source and committed JSON, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. When the checkpoint follows no successful image-load or measurement call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested original or annotated image cannot be resolved, does not belong to the Session inventory, or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every distinct image loaded by the immediately preceding batch resolves from the authorized same-Session inventory and the assembled request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those original image bytes held only in memory

#### Scenario: Assemble a valid request after measurement
- **WHEN** each successful measurement in the immediately preceding batch has a matching committed result and its authorized source image can be resolved for annotation
- **THEN** Figura assembles and validates the matching annotated images and may claim and dispatch the Provider attempt within Provider limits

#### Scenario: Assemble a request without a preceding image call
- **WHEN** the current checkpoint follows Run creation or a tool batch without a successful `load_image` or Cartesian measurement result
- **THEN** Figura assembles and validates the text and tool history without resolving Attachment or Panel bytes

#### Scenario: An image required for visual feedback cannot be resolved
- **WHEN** a successful `load_image` or measurement result refers to a missing, unreadable, invalid, or differently owned image needed by the next request
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request

#### Scenario: Images exceed Provider bounds
- **WHEN** original and annotated images for the immediately preceding tool batch exceed Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt
