## MODIFIED Requirements

### Requirement: Gateway is available only as a local HTTP service
The system SHALL provide a versioned loopback HTTP/JSON Gateway with bounded
Agent readiness for each supported provider. Health responses MAY identify
`openai`, `qwen`, and `deepseek`, the safe availability state of each, and the
default provider, but MUST NOT expose credentials, raw endpoint values, or
provider payloads.

#### Scenario: Health reports provider capabilities
- **WHEN** a local client requests Gateway health
- **THEN** it receives HTTP service status plus bounded per-provider readiness and the default provider

#### Scenario: Provider readiness is unavailable
- **WHEN** one provider lacks valid server configuration
- **THEN** health reports that provider as unavailable with a stable safe reason while the Gateway remains diagnosable

#### Scenario: Unsupported provider request is bounded
- **WHEN** a client submits an unsupported provider value
- **THEN** the Gateway returns a structured validation error without traceback, secrets, or starting a run

### Requirement: Gateway executes a text turn in a named session
The Gateway SHALL accept an optional bounded provider on synchronous and
asynchronous text-turn requests. It SHALL resolve the provider before starting
the Agent, snapshot the effective provider and model on the run, and preserve
the existing transcript and attachment behavior. Omitting provider SHALL use
the configured default provider. A selected provider that is unavailable SHALL
fail before Agent execution with a safe configuration error. An asynchronous
request MAY include an idempotency key and bounded request fingerprint;
repeated equivalent requests SHALL resolve to the same run, while a conflicting
reuse SHALL fail before execution. The Gateway SHALL expose an authorized
operation to interrupt an active run and SHALL preserve its bounded terminal
reason.

#### Scenario: Run uses the requested provider
- **WHEN** a valid run request specifies `openai`, `qwen`, or `deepseek`
- **THEN** the accepted run and Agent runtime use that provider's configuration and the run metadata identifies the selected provider

#### Scenario: Omitted provider uses the default
- **WHEN** a valid run request omits provider
- **THEN** the Gateway uses the configured default provider and records the effective value on the run

#### Scenario: Provider selection does not expose secrets
- **WHEN** a run request contains provider selection
- **THEN** only the bounded provider identifier is accepted from the client; client-supplied key, endpoint, model, or arbitrary provider body is ignored or rejected

#### Scenario: Unavailable provider does not start execution
- **WHEN** the selected provider is unavailable
- **THEN** the Gateway returns or emits `agent_unavailable` with a safe reason, preserves prior history, and does not invoke the Agent

#### Scenario: Successful synchronous text turn is returned
- **WHEN** a client submits valid text to the existing synchronous message operation for an existing named session and the Agent completes
- **THEN** the response contains the submitted user text and final assistant answer in chronological order and increments the session's completed-run count

#### Scenario: Asynchronous text turn is accepted
- **WHEN** a client submits valid text and optional attachment IDs to the run-oriented operation for an existing named session
- **THEN** the Gateway returns a run ID and initial running state before the Agent has completed, and the run remains associated with that session

#### Scenario: Asynchronous run completes
- **WHEN** an accepted run reaches a final answer
- **THEN** the run emits a terminal success event and the session transcript becomes readable with the completed user and assistant records

#### Scenario: Agent configuration failure is isolated and safe
- **WHEN** provider setup fails because the Agent configuration is missing or invalid
- **THEN** the Gateway emits or returns a bounded `agent_unavailable` failure with a stable safe reason code, does not include credentials or raw exception text, marks the run unsuccessful, and keeps prior completed session history readable

#### Scenario: Agent execution failure is isolated
- **WHEN** the configured Agent fails while executing a provider request or tool-capable run
- **THEN** the Gateway emits or returns a bounded Agent execution failure, marks the run unsuccessful, and keeps prior completed session history readable

#### Scenario: Empty message is rejected before execution
- **WHEN** a client submits blank or whitespace-only text
- **THEN** the Gateway returns a validation error and does not create or begin an Agent run

#### Scenario: Equivalent asynchronous submission returns the original run
- **WHEN** a client repeats an accepted asynchronous request with the same idempotency key and equivalent bounded request data
- **THEN** the Gateway returns the original run ID and state and does not enqueue or invoke another Agent

#### Scenario: Conflicting idempotency reuse is rejected
- **WHEN** a client reuses an idempotency key with different text, attachments, provider, or session
- **THEN** the Gateway returns a bounded conflict response and neither the original run nor a new run is changed

#### Scenario: Active run can be interrupted
- **WHEN** an authorized client requests interruption for an active run
- **THEN** the Gateway records a user-cancel reason, signals the running Agent, and exposes the interrupted terminal state through the run summary and event stream
