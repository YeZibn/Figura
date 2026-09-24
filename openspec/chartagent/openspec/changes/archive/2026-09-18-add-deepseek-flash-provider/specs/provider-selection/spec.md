## MODIFIED Requirements

### Requirement: Provider selection is bounded and server-owned
The system SHALL support exactly the provider identifiers `openai`, `qwen`, and
`deepseek`. A browser or desktop client MAY submit only the provider
identifier; API keys, base URLs, models, and provider-specific request bodies
MUST remain owned and resolved by the local Gateway.

#### Scenario: Accepted provider is forwarded
- **WHEN** a client submits a run with provider `openai`, `qwen`, or `deepseek`
- **THEN** the Gateway accepts the provider identifier and resolves its own configured credentials and endpoint for that provider

#### Scenario: Provider injection is rejected
- **WHEN** a client submits an empty, unknown, credential-bearing, or otherwise unsupported provider value
- **THEN** the Gateway rejects the request with a bounded validation error and does not start an Agent run

### Requirement: Provider selection is snapshotted per run
The system SHALL resolve and persist the effective provider for a run when the
run is accepted. Changing the frontend selection afterward MUST affect only a
later run and MUST NOT change the provider of an active or completed run.

#### Scenario: Selection applies to the next run
- **WHEN** the user changes the provider selection before submitting a message
- **THEN** the next accepted run uses and records the newly selected provider

#### Scenario: Active run keeps its provider
- **WHEN** the user changes the selection while a run is executing
- **THEN** the active run continues with its original provider and the new selection is used only by a later run

### Requirement: Provider availability is safely discoverable
The Gateway SHALL expose bounded availability information for all supported
providers without returning API keys, raw endpoint values, or provider error
payloads. An unavailable provider MUST remain selectable only if the client can
show an actionable unavailable state and the run is rejected before execution.

#### Scenario: Health reports configured providers
- **WHEN** the frontend requests Gateway health
- **THEN** the response identifies `openai`, `qwen`, and `deepseek` provider names when supported by the deployment, safe availability states, and the configured default provider without secrets

#### Scenario: Unconfigured provider is selected
- **WHEN** a client selects a provider whose required server configuration is unavailable
- **THEN** the Gateway returns a stable configuration error and preserves prior session history
