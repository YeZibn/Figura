## MODIFIED Requirements

### Requirement: Gateway is available only as a local HTTP service

The system SHALL provide a versioned HTTP/JSON gateway bound to a loopback interface. It SHALL expose a health response that identifies HTTP Gateway availability and a bounded Agent readiness status without exposing credentials or provider payloads. It SHALL reject malformed JSON, unsupported methods, and unsupported routes with JSON error responses. The gateway MUST NOT bind to a non-loopback address by default.

#### Scenario: Local client verifies gateway and Agent availability

- **WHEN** a local desktop or browser client requests the gateway health endpoint
- **THEN** it receives a successful JSON response identifying a compatible gateway version, HTTP service status, and a safe Agent readiness state

#### Scenario: Agent configuration is missing

- **WHEN** the Gateway is running but required provider configuration is unavailable
- **THEN** the health response remains usable for diagnosing the local service, reports Agent readiness as unavailable with a stable safe reason code, and contains no credential value or raw exception

#### Scenario: Unsupported request is bounded

- **WHEN** a client sends malformed JSON, an unsupported method, or an unknown route
- **THEN** the gateway returns a JSON error with an appropriate client error status and no traceback or credential material

### Requirement: Gateway executes a text turn in a named session

The gateway SHALL accept a non-empty text message and optional authorized attachment IDs for a named session, execute the existing tool-capable Agent against that session, and support both the existing synchronous response and an asynchronous run-oriented response. The synchronous operation SHALL remain available for compatibility and return the refreshed completed transcript with the resulting final answer. The asynchronous operation SHALL return a stable opaque run ID before Agent completion and expose the run's eventual terminal result through the run protocol. Only completed runs SHALL enter the session's completed transcript.

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
