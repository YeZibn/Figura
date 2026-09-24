## MODIFIED Requirements

### Requirement: Gateway is available only as a local HTTP service

The system SHALL provide a versioned loopback HTTP/JSON Gateway with bounded
Agent readiness for each supported provider. Health responses MAY identify
`openai` and `qwen`, the safe availability state of each, and the default
provider, but MUST NOT expose credentials, raw endpoint values, or provider
payloads.

#### Scenario: Health reports provider capabilities

- **WHEN** a local client requests Gateway health
- **THEN** it receives HTTP service status plus bounded per-provider readiness
  and the default provider

#### Scenario: Provider readiness is unavailable

- **WHEN** one provider lacks valid server configuration
- **THEN** health reports that provider as unavailable with a stable safe reason
  while the Gateway remains diagnosable

#### Scenario: Unsupported provider request is bounded

- **WHEN** a client submits an unsupported provider value
- **THEN** the Gateway returns a structured validation error without traceback,
  secrets, or starting a run

### Requirement: Gateway executes a text turn in a named session

The Gateway SHALL accept an optional bounded provider on synchronous and
asynchronous text-turn requests. It SHALL resolve the provider before starting
the Agent, snapshot the effective provider and model on the run, and preserve
the existing transcript and attachment behavior. Omitting provider SHALL use
the configured default provider. A selected provider that is unavailable SHALL
fail before Agent execution with a safe configuration error.

#### Scenario: Run uses the requested provider

- **WHEN** a valid run request specifies `qwen`
- **THEN** the accepted run and Agent runtime use Qwen configuration and the
  run metadata identifies `qwen`

#### Scenario: Omitted provider uses the default

- **WHEN** a valid run request omits provider
- **THEN** the Gateway uses the configured default provider and records the
  effective value on the run

#### Scenario: Provider selection does not expose secrets

- **WHEN** a run request contains provider selection
- **THEN** only the bounded provider identifier is accepted from the client;
  client-supplied key, endpoint, model, or arbitrary provider body is ignored or
  rejected

#### Scenario: Unavailable provider does not start execution

- **WHEN** the selected provider is unavailable
- **THEN** the Gateway returns or emits `agent_unavailable` with a safe reason,
  preserves prior history, and does not invoke the Agent

### Requirement: Gateway exposes a bounded ordered run event stream

Run summaries, live events, and historical events SHALL include the effective
provider and model where available, using bounded machine fields. These fields
MUST remain stable after acceptance and MUST NOT contain credentials, endpoint
URLs, or raw provider responses.

#### Scenario: Live event identifies provider

- **WHEN** a run emits its start or model-turn event
- **THEN** the event exposes the snapshotted provider and model for safe UI
  presentation

#### Scenario: Reload preserves provider metadata

- **WHEN** a client retrieves a completed or failed run history
- **THEN** the run summary and relevant events retain the same provider and
  model metadata
