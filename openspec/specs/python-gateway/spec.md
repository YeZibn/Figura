# python-gateway Specification

## Purpose

Provide a local, browser-compatible gateway that lets the ChartAgent desktop client work with durable named Agent sessions and completed text runs without exposing Python internals or SQLite directly.

## Requirements

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

### Requirement: Gateway exposes named session lifecycle and transcript reads

The gateway SHALL provide JSON operations to list named sessions, create a named session, and retrieve a named session's completed text transcript. Session summaries SHALL include a stable opaque identifier, display name, update timestamp, and completed-run count. A transcript response SHALL contain session metadata and ordered user and assistant text records from completed runs.

#### Scenario: Client lists available sessions

- **WHEN** a client requests the named-session collection
- **THEN** the gateway returns sessions in most-recently-updated order with bounded summary fields

#### Scenario: Client creates a session

- **WHEN** a client submits a valid unused session name
- **THEN** the gateway creates and returns an empty named session

#### Scenario: Duplicate or missing session is explicit

- **WHEN** a client creates a duplicate name or requests an unknown session identifier
- **THEN** the gateway returns a structured conflict or not-found error without changing another session

#### Scenario: Transcript excludes unfinished runs

- **WHEN** a stored session has an interrupted or failed run
- **THEN** its transcript response excludes that run's partial conversation records

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

### Requirement: Gateway exposes a bounded ordered run event stream

The Gateway SHALL expose a local event stream for an accepted run. Events SHALL carry the run ID, a monotonically increasing sequence, a bounded event name and payload, and enough session-safe metadata for a client to render model turns, tool calls, tool results, visual observations, final answers, and failures in execution order. A run SHALL emit exactly one terminal success or failure event.

#### Scenario: Tool trajectory is streamed

- **WHEN** an Agent run performs a model turn and invokes a tool
- **THEN** the stream emits ordered model, tool-call, and tool-result events with bounded tool names, call identifiers, arguments, and result summaries

#### Scenario: Visual observation is streamed safely

- **WHEN** a tool produces a valid generated visual observation
- **THEN** the stream emits a caption, media type, bounded dimensions or size metadata, and an opaque temporary observation ID without embedding raw image bytes or data URLs in the event JSON

#### Scenario: Client reconnects to an active run

- **WHEN** a client reconnects to a run event stream using a previously observed sequence
- **THEN** the Gateway replays available later events in order or reports that the run is no longer available, without duplicating or mutating completed transcript records

#### Scenario: Event payload exceeds a configured limit

- **WHEN** reasoning, tool arguments, tool results, or other event content exceeds its configured display limit
- **THEN** the Gateway sends a bounded representation with an explicit truncation marker and never sends credentials, raw provider responses, or unbounded data

### Requirement: Gateway serves temporary visual observations by authorized reference

The Gateway MAY expose generated visual observation bytes through a separate loopback resource addressed by an opaque observation ID. Such resources SHALL be bound to the owning run and session, bounded by media type and size, expire after the run's retention window, and SHALL NOT be written to durable session memory.

#### Scenario: Authorized observation is fetched

- **WHEN** the active session requests an observation ID received for its run
- **THEN** the Gateway returns the bounded image bytes with the declared media type

#### Scenario: Observation access is unauthorized or expired

- **WHEN** a different session, unknown ID, or expired ID requests an observation
- **THEN** the Gateway returns a bounded not-found or unauthorized error without revealing source paths or image content

### Requirement: Gateway contract is safe and replaceable for the desktop client

Gateway responses SHALL use documented JSON fields independent of Python classes, SQLite rows, provider responses, raw traces, credentials, local file paths, attachment bytes, and generated image bytes. The desktop client SHALL be able to select the gateway adapter explicitly while preserving its mock adapter for offline development.

#### Scenario: Gateway mode replaces mock session operations

- **WHEN** the desktop client is configured for gateway mode and the local gateway is healthy
- **THEN** session listing, session creation, session reading, and text submission use the gateway contract rather than mock data

#### Scenario: Offline mock mode remains available

- **WHEN** the desktop client is configured for mock mode
- **THEN** it remains usable without a running gateway or provider configuration

#### Scenario: Sensitive and binary data are absent

- **WHEN** a gateway response represents a session or completed run that involved tools or attachments
- **THEN** it contains no credentials, raw provider payloads, local source paths, image bytes, data URLs, or unbounded trace payloads
