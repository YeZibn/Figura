## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from all earlier terminal Runs in the same Session, ordered by Run ordinal, followed by the current Run's immutable input, validated images referenced by each included input, committed model responses, and committed tool results. Each Run input SHALL appear as a user message containing persisted text followed by image blocks in the exact order of its persisted attachment IDs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A final-answer fact that references a response SHALL NOT add a duplicate message. A provider-private continuation SHALL be attached only to its originating assistant response in the current Run and SHALL NOT be carried across Run boundaries. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request
- **WHEN** the checkpoint points to the initial model action after Run creation and the Session has no earlier Runs
- **THEN** the request contains the fixed v1 instruction, the persisted user text followed by its referenced images in persisted order, and the Run's explicit provider/model selection

#### Scenario: Include earlier Session Runs before the current Run
- **WHEN** the checkpoint points to a model action and the Session has earlier terminal Runs
- **THEN** the request contains all earlier Run messages in ascending Run ordinal followed by the current Run's input and committed progress

#### Scenario: Rebuild a completed tool round
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch
- **THEN** the request contains the original user text and images, the assistant tool-call message, and all matching tool result messages in their committed order, with continuation attached only to the correct assistant message from the current Run

#### Scenario: History contains an unresolved tool attempt
- **WHEN** the current Run or an earlier Run contains a tool attempt without a committed result
- **THEN** Figura does not construct or dispatch a model request from that incomplete interaction

#### Scenario: Historical tool registry is unavailable
- **WHEN** the current registry does not match the registry version recorded by a committed tool batch in the current or an earlier Run
- **THEN** Figura fails closed without dispatching a provider request or a tool

#### Scenario: Do not carry continuation across Runs
- **WHEN** an earlier Run's response has provider-private continuation data
- **THEN** Figura includes the normalized response and committed tool facts in Session history but omits that continuation from the later Run's Provider request

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable provider attempt is claimed, Figura SHALL resolve every attachment referenced by the current Run input and every earlier Run input included in Session history using the owning Session ID, assemble the complete Provider request, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. Figura SHALL NOT claim or dispatch a provider attempt when an attachment cannot be resolved or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid bounded image request
- **WHEN** all current and historical image references resolve and the assembled request is within Provider image and request limits
- **THEN** Figura may claim the provider attempt and dispatch the request with image bytes held only in memory for the Provider call

#### Scenario: An image reference cannot be resolved
- **WHEN** a current or historical Run references a missing, unreadable, invalid, or differently owned image file
- **THEN** Figura fails the current Run before claiming a provider attempt and sends no request to the Provider

#### Scenario: Images exceed Provider request bounds
- **WHEN** current and historical images exceed the Provider image count, individual image size, aggregate image size, or another request limit
- **THEN** Figura fails the current Run before claiming a provider attempt and sends no request to the Provider

## REMOVED Requirements

### Requirement: Agent requests preserve complete recent context within provider limits
**Reason**: This request policy permits removing older committed interactions, which conflicts with complete Session history.
**Migration**: Use the added requirement `Agent requests preserve complete Session history within Provider limits`; requests that exceed hard Provider limits now fail before Provider-attempt claim without trimming.

## ADDED Requirements

### Requirement: Agent requests preserve complete Session history within Provider limits
Figura SHALL submit non-streaming requests using one fixed v1 system instruction, the provider-neutral tool projection for the selected registry, and bounded completion options. A request SHALL contain complete same-Session history and SHALL satisfy the Provider boundary's message, instruction, tool, image, and total text/schema limits before a durable provider attempt is claimed. Figura SHALL NOT truncate, summarize, or remove any historical Run or interaction to fit a request. If the complete request exceeds any Provider limit, Figura SHALL fail the current Run before claiming or dispatching a provider attempt.

#### Scenario: Send every complete Session interaction
- **WHEN** all earlier same-Session Runs have valid complete histories and the assembled request is within Provider limits
- **THEN** Figura sends the entire earlier history and current Run prefix in ordinal and committed fact order

#### Scenario: Complete history exceeds a Provider limit
- **WHEN** the full request exceeds a Provider message, instruction, tool, image, text, or schema limit
- **THEN** Figura preserves all source facts, fails the current Run, and makes no Provider-attempt claim or network request

#### Scenario: Keep a tool result associated with its call
- **WHEN** a successful or failed tool result is projected into Provider history
- **THEN** Figura sends a bounded JSON observation in a tool message associated with the original call ID and omits implementation details from an error observation
