## MODIFIED Requirements

### Requirement: Provider history is reconstructed from complete committed interactions
For each model action, Figura SHALL build the conversation from the Run's immutable input, the validated images referenced by that input, committed model responses, and committed tool results. The original user message SHALL contain the persisted text followed by image blocks in the exact order of the persisted attachment IDs. Each model response containing tool calls SHALL be represented by one assistant message whose calls preserve provider order, followed by one tool message for every corresponding result with the matching opaque call ID. A provider-private continuation SHALL be attached only to its originating assistant response. Figura SHALL NOT send a partial tool batch, invent a missing result, include an unresolved tool attempt as a result, or expose continuation data in public projections or ordinary diagnostics.

#### Scenario: Build the first model request
- **WHEN** the checkpoint points to the initial model action after Run creation
- **THEN** the request contains the fixed v1 instruction, the persisted user text followed by its referenced images in persisted order, and the Run's explicit provider/model selection

#### Scenario: Rebuild a completed tool round
- **WHEN** the checkpoint points to a model action after a fully resolved tool batch
- **THEN** the request contains the original user text and images, the assistant tool-call message, and all matching tool result messages in their committed order, with continuation attached to the correct assistant message

#### Scenario: History contains an unresolved tool attempt
- **WHEN** a Run's current checkpoint points to a tool attempt without a committed result
- **THEN** Figura does not construct a later model request from that incomplete interaction

#### Scenario: Historical tool registry is unavailable
- **WHEN** the current registry does not match the registry version recorded by a committed tool batch
- **THEN** Figura fails closed without dispatching a provider request or a tool

## ADDED Requirements

### Requirement: Referenced images are resolved and bounded before provider-attempt claim
Before a durable provider attempt is claimed, Figura SHALL resolve every Run input attachment using the Run's Session ID, assemble the Provider request, and validate image count, individual byte size, aggregate image byte size, and all other Provider limits. Figura SHALL NOT claim or dispatch a provider attempt when an attachment cannot be resolved or the assembled request exceeds a Provider limit.

#### Scenario: Assemble a valid bounded image request
- **WHEN** all persisted image references resolve and the assembled request is within Provider image and request limits
- **THEN** Figura may claim the provider attempt and dispatch the request with image bytes held only in memory for the Provider call

#### Scenario: An image reference cannot be resolved
- **WHEN** a Run references a missing, unreadable, or invalid image file
- **THEN** Figura fails the Run before claiming a provider attempt and sends no request to the Provider

#### Scenario: Images exceed Provider request bounds
- **WHEN** referenced images exceed the Provider image count, individual image size, aggregate image size, or another request limit
- **THEN** Figura fails the Run before claiming a provider attempt and sends no request to the Provider
