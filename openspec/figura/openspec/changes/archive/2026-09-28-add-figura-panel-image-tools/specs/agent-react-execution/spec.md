## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, committed model responses, and committed tool results. Each Run input SHALL appear once as a user message containing its persisted text and ordered attachment references as text identities; it SHALL NOT automatically include image blocks. The request SHALL include a text inventory of every available attachment and committed Panel in the target Run's `RunExecutionState`, including same-Session attachments referenced only by earlier terminal Runs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. Only image blocks explicitly loaded by successful `load_image` calls in the immediately preceding fully committed tool batch may be appended to the request, in tool-call order. A provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request with multiple attachments
- **WHEN** the checkpoint points to the initial model action and the current Run references multiple images
- **THEN** the request contains the fixed v1 instruction, the persisted user text, and a complete textual image inventory, but no image bytes

#### Scenario: Include earlier Session Runs and their attachments
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs with referenced attachments
- **THEN** the request contains all earlier Run messages in ascending Run ordinal, preserves their text and attachment IDs, lists their images in the available-image inventory, and does not attach their historical image bytes

#### Scenario: Rebuild a completed tool round with explicitly loaded images
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch containing one or more successful `load_image` calls
- **THEN** the request contains the original ordered assistant/tool interaction and attaches each loaded image once after the text inventory in the persisted tool-call order

#### Scenario: Do not repeat images from an older tool batch
- **WHEN** the latest completed tool batch contains no successful `load_image` call, even though an earlier batch or Run loaded an image
- **THEN** the request contains no image bytes from that earlier batch or Run

#### Scenario: History contains an unresolved tool attempt
- **WHEN** the current Run or an earlier Run contains a tool attempt without a committed result
- **THEN** Figura does not construct or dispatch a model request from that incomplete interaction

#### Scenario: Historical tool registry is unavailable
- **WHEN** the current registry does not match the registry version recorded by a committed tool batch in the current or an earlier Run
- **THEN** Figura fails closed without dispatching a provider request or a tool

#### Scenario: Do not carry continuation across Runs
- **WHEN** an earlier Run's response has provider-private continuation data
- **THEN** Figura includes the normalized assistant response and committed tool facts in Session history but omits that continuation from the later Run's Provider request

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable Provider attempt is claimed, Figura SHALL derive the authorized attachment and Panel inventories from the target Run's `RunExecutionState`, resolve only the successful `load_image` results in the immediately preceding fully committed tool batch, assemble their bytes as user-role image blocks, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. If the checkpoint follows no `load_image` call, the request SHALL contain no image bytes. Figura SHALL NOT claim or dispatch a Provider attempt when a requested image cannot be resolved, does not belong to the Session inventory, or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid request after explicit image loads
- **WHEN** every distinct image loaded by the immediately preceding tool batch resolves from the authorized same-Session inventory and the request is within Provider limits
- **THEN** Figura may claim the Provider attempt and dispatch the request with those image bytes held only in memory

#### Scenario: Assemble a request without a preceding image load
- **WHEN** the current checkpoint follows Run creation or a tool batch without a successful `load_image` result
- **THEN** Figura assembles and validates the text and tool history without resolving any attachment or Panel bytes

#### Scenario: An explicitly loaded image cannot be resolved
- **WHEN** a successful `load_image` result refers to a missing, unreadable, invalid, or differently owned image
- **THEN** Figura fails the current Run before claiming a Provider attempt and sends no request to the Provider

#### Scenario: Explicitly loaded images exceed Provider bounds
- **WHEN** images loaded by the immediately preceding tool batch exceed the Provider image count, per-image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming or dispatching a Provider attempt
