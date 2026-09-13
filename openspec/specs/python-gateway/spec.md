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

The gateway SHALL provide JSON operations to list named sessions, create a
named session, delete a named session, and retrieve a named session's
completed text transcript together with its persisted run summaries when
requested. Session summaries SHALL include a stable opaque identifier,
display name, update timestamp, and completed-run count. A transcript response
SHALL contain session metadata and ordered user and assistant text records
from completed runs without requiring execution events to be embedded in model
messages. Deletion SHALL be addressed by session ID, reject active sessions,
and remove all durable child records and managed execution artifacts.

#### Scenario: Client lists available sessions

- **WHEN** a client requests the named-session collection
- **THEN** the gateway returns sessions in most-recently-updated order with bounded summary fields

#### Scenario: Client creates a session

- **WHEN** a client submits a valid unused session name
- **THEN** the gateway creates and returns an empty named session

#### Scenario: Client deletes an idle session

- **WHEN** a client deletes an existing session ID with no active run
- **THEN** the gateway removes the session, its runs, records, attachments,
  execution events, and managed visual artifacts, and returns a bounded success
  response

#### Scenario: Duplicate, missing, or busy session is explicit

- **WHEN** a client creates a duplicate name, requests an unknown session identifier, or attempts to delete a session with an active run
- **THEN** the gateway returns a structured conflict or not-found error without changing another session

#### Scenario: Transcript excludes unfinished runs

- **WHEN** a stored session has an interrupted or failed run
- **THEN** its completed text transcript excludes that run's partial
  conversation records while its run summary and available execution history
  remain queryable as incomplete or failed

### Requirement: Gateway serves persistent attachment content by authorized reference

The Gateway SHALL expose a session-scoped content resource for registered attachments. Before returning bytes, it MUST verify session ownership, source existence, readability, supported media type, configured size limit, and unchanged content hash. Successful responses SHALL contain only bounded image bytes with the validated media type; failures SHALL use structured bounded errors without source paths.

#### Scenario: Authorized attachment content is fetched

- **WHEN** the active session requests content for an available attachment ID
- **THEN** the Gateway returns the source image bytes with its validated media type and no filesystem metadata

#### Scenario: Attachment content is unauthorized or invalid

- **WHEN** a different session requests the attachment, or the source is missing, changed, oversized, unreadable, or unsupported
- **THEN** the Gateway returns a bounded not-found, unauthorized, or unavailable error and no image bytes

### Requirement: Gateway deletes attachments and their source files

The Gateway SHALL provide a session-scoped attachment deletion operation. It SHALL verify ownership, remove the durable attachment metadata, and remove the corresponding source file only when the path is inside the managed attachment root. Deletion SHALL not remove files outside that root.

#### Scenario: Authorized attachment is deleted

- **WHEN** a client deletes an attachment ID belonging to an existing session
- **THEN** the Gateway removes its metadata and managed source bytes, and later content or load requests fail as unavailable or not found

#### Scenario: Cross-session attachment deletion is rejected

- **WHEN** a client uses an attachment ID belonging to another session
- **THEN** the Gateway returns a bounded not-found or unauthorized error and preserves the attachment

#### Scenario: Session deletion removes its attachment directory

- **WHEN** an idle session is deleted
- **THEN** the Gateway removes managed source files owned by that session after the durable session deletion succeeds

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

The Gateway SHALL expose a local event stream and historical event retrieval
for an accepted run. Events SHALL carry the run ID, a monotonically increasing
sequence, a bounded event name and payload, and enough session-safe metadata
for a client to render model turns, progress content when available, tool
calls, tool results, visual observations, final answers, and failures in
execution order. Events SHALL be persisted for the configured run-history
retention policy. A run SHALL emit exactly one terminal success or failure
event.

#### Scenario: Tool trajectory is streamed

- **WHEN** an Agent run performs a model turn and invokes a tool
- **THEN** the live stream and later history expose ordered model, tool-call,
  and tool-result events with bounded tool names, call identifiers, arguments,
  and result summaries

#### Scenario: Visual observation is streamed safely

- **WHEN** a tool produces a valid generated visual observation
- **THEN** the stream emits a caption, media type, bounded dimensions or size metadata, and an opaque temporary observation ID without embedding raw image bytes or data URLs in the event JSON

#### Scenario: Client hydrates and reconnects by sequence

- **WHEN** a client opens or reconnects to a run using a previously observed
  sequence
- **THEN** the Gateway returns available events after that sequence in order,
  followed by live events when the run is active
- **AND** it does not duplicate events or mutate completed transcript records

#### Scenario: History gap is explicit

- **WHEN** the requested sequence is older than the retained event history or
  the run is no longer available
- **THEN** the Gateway returns a bounded history-gap or run-unavailable result
- **AND** it does not make the client infer a complete trajectory from partial
  events

#### Scenario: Event payload exceeds a configured limit

- **WHEN** reasoning, tool arguments, tool results, or other event content exceeds its configured display limit
- **THEN** the Gateway sends a bounded representation with an explicit truncation marker and never sends credentials, raw provider responses, or unbounded data

### Requirement: Gateway serves temporary visual observations by authorized reference

The Gateway SHALL expose generated visual observation bytes through a
session-and-run-scoped resource addressed by an opaque observation ID. The
metadata and artifact SHALL follow the configured persistence and retention
policy, SHALL be bounded by media type and size, and SHALL not expose source
paths or raw image bytes in event JSON. Deleting the owning session or run
history SHALL remove the managed artifact when policy permits.

#### Scenario: Authorized observation is fetched

- **WHEN** the active session requests an observation ID received for its run
- **THEN** the Gateway returns the bounded image bytes with the declared media
  type while preserving the associated event metadata

#### Scenario: Observation access is unauthorized or expired

- **WHEN** a different session, unknown ID, or expired ID requests an observation
- **THEN** the Gateway returns a bounded not-found or unauthorized error without revealing source paths or image content

#### Scenario: Persisted observation survives ordinary reload

- **WHEN** a completed run is reopened within the configured artifact retention
  policy
- **THEN** its observation metadata remains readable and its managed preview is
  fetchable through the authorized reference

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

### Requirement: Gateway serves generated chart artifacts by authorized reference

The Gateway SHALL persist and serve successful user-facing generated chart
artifacts through an opaque reference scoped to the owning session and run.
Artifact metadata SHALL include a bounded media type, byte count, dimensions,
chart type, and caption or title. Gateway responses SHALL not expose local
paths or raw image bytes in JSON.

#### Scenario: Generated chart is returned to its owning session

- **WHEN** a client requests a generated chart reference belonging to the
  active session and run
- **THEN** the Gateway returns the bounded image bytes with the declared media
  type and preserves the associated metadata

#### Scenario: Generated chart metadata is included in run history

- **WHEN** a run successfully produces a generated chart
- **THEN** its event history exposes the artifact reference and bounded
  metadata in execution order
- **AND** the client can distinguish it from a temporary model observation

#### Scenario: Generated chart survives ordinary reload

- **WHEN** a completed run is reopened within the configured artifact retention
  policy
- **THEN** the generated chart metadata remains readable and its artifact can
  be fetched through the authorized reference

#### Scenario: Generated chart access is isolated and bounded

- **WHEN** a different session, unknown reference, expired artifact, or an
  artifact over the configured output limit is requested
- **THEN** the Gateway returns a bounded not-found, unauthorized, expired, or
  unavailable error without revealing source paths or image content in JSON

#### Scenario: Session deletion removes generated charts

- **WHEN** the owning idle session is deleted
- **THEN** its generated chart artifacts and metadata are no longer readable
- **AND** another session's generated chart artifacts remain available
