## MODIFIED Requirements

### Requirement: Gateway exposes named session lifecycle and transcript reads

The gateway SHALL provide JSON operations to list named sessions, create a
named session, delete a named session, and retrieve a named session's
completed text transcript together with its persisted run summaries when
requested. Session summaries SHALL include a stable opaque identifier, display
name, update timestamp, and completed-run count. A transcript response SHALL
contain session metadata and ordered user and assistant text records from
completed runs without requiring execution events to be embedded in model
messages. Deletion SHALL be addressed by session ID, reject active sessions,
and remove all durable child records and managed execution artifacts.

#### Scenario: Client lists available sessions

- **WHEN** a client requests the named-session collection
- **THEN** the gateway returns sessions in most-recently-updated order with
  bounded summary fields

#### Scenario: Client creates a session

- **WHEN** a client submits a valid unused session name
- **THEN** the gateway creates and returns an empty named session

#### Scenario: Client deletes an idle session

- **WHEN** a client deletes an existing session ID with no active run
- **THEN** the gateway removes the session, its runs, records, attachments,
  execution events, and managed visual artifacts, and returns a bounded success
  response

#### Scenario: Duplicate, missing, or busy session is explicit

- **WHEN** a client creates a duplicate name, requests an unknown session
  identifier, or attempts to delete a session with an active run
- **THEN** the gateway returns a structured conflict or not-found error without
  changing another session

#### Scenario: Transcript excludes unfinished runs

- **WHEN** a stored session has an interrupted or failed run
- **THEN** its completed text transcript excludes that run's partial
  conversation records while its run summary and available execution history
  remain queryable as incomplete or failed

### Requirement: Gateway exposes a bounded ordered run event stream

The Gateway SHALL expose a local event stream and historical event retrieval
for an accepted run. Events SHALL carry the run ID, a monotonically increasing
sequence, a bounded event name and payload, and enough session-safe metadata for
a client to render model turns, progress content when available, tool calls,
tool results, visual observations, final answers, and failures in execution
order. Events SHALL be persisted for the configured run-history retention
policy. A run SHALL emit exactly one terminal success or failure event.

#### Scenario: Tool trajectory is streamed and retained

- **WHEN** an Agent run performs a model turn and invokes a tool
- **THEN** the live stream and later history expose ordered model, tool-call,
  and tool-result events with bounded tool names, call identifiers, arguments,
  and result summaries

#### Scenario: Visual observation is streamed safely

- **WHEN** a tool produces a valid generated visual observation
- **THEN** the stream and historical event record expose a caption, media type,
  bounded size metadata, and an opaque observation ID without embedding raw
  image bytes or data URLs in event JSON

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

- **WHEN** reasoning, progress content, tool arguments, tool results, or other
  event content exceeds its configured display limit
- **THEN** the Gateway sends and persists a bounded representation with an
  explicit truncation marker and never sends credentials, raw provider
  responses, or unbounded data

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

- **WHEN** a different session, unknown ID, or expired observation requests the
  resource
- **THEN** the Gateway returns a bounded not-found or unauthorized error
  without revealing source paths or image content

#### Scenario: Persisted observation survives ordinary reload

- **WHEN** a completed run is reopened within the configured artifact retention
  policy
- **THEN** its observation metadata remains readable and its managed preview is
  fetchable through the authorized reference
