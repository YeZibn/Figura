# python-gateway Specification

## Purpose

Provide a local, browser-compatible gateway that lets the ChartAgent desktop client work with durable named Agent sessions and completed text runs without exposing Python internals or SQLite directly.

## Requirements

### Requirement: Gateway is available only as a local HTTP service

The system SHALL provide a versioned loopback HTTP/JSON Gateway with bounded
Agent readiness for each supported provider. Health responses MAY identify
`openai`, `qwen`, and `deepseek`, the safe availability state of each, and the
default provider, but MUST NOT expose credentials, raw endpoint values, or
provider payloads.

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
- **THEN** the accepted run and Agent runtime use that provider's configuration
  and the run metadata identifies the selected provider

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

#### Scenario: Successful synchronous text turn is returned

- **WHEN** a client submits valid text to the existing synchronous message
  operation for an existing named session and the Agent completes
- **THEN** the response contains the submitted user text and final assistant
  answer in chronological order and increments the session's completed-run
  count

#### Scenario: Asynchronous text turn is accepted

- **WHEN** a client submits valid text and optional attachment IDs to the
  run-oriented operation for an existing named session
- **THEN** the Gateway returns a run ID and initial running state before the
  Agent has completed, and the run remains associated with that session

#### Scenario: Asynchronous run completes

- **WHEN** an accepted run reaches a final answer
- **THEN** the run emits a terminal success event and the session transcript
  becomes readable with the completed user and assistant records

#### Scenario: Agent configuration failure is isolated and safe

- **WHEN** provider setup fails because the Agent configuration is missing or
  invalid
- **THEN** the Gateway emits or returns a bounded `agent_unavailable` failure
  with a stable safe reason code, does not include credentials or raw exception
  text, marks the run unsuccessful, and keeps prior completed session history
  readable

#### Scenario: Agent execution failure is isolated

- **WHEN** the configured Agent fails while executing a provider request or
  tool-capable run
- **THEN** the Gateway emits or returns a bounded Agent execution failure,
  marks the run unsuccessful, and keeps prior completed session history
  readable

#### Scenario: Empty message is rejected before execution

- **WHEN** a client submits blank or whitespace-only text
- **THEN** the Gateway returns a validation error and does not create or begin
  an Agent run

#### Scenario: Equivalent asynchronous submission returns the original run

- **WHEN** a client repeats an accepted asynchronous request with the same
  idempotency key and equivalent bounded request data
- **THEN** the Gateway returns the original run ID and state
- **AND** it does not enqueue or invoke another Agent

#### Scenario: Conflicting idempotency reuse is rejected

- **WHEN** a client reuses an idempotency key with different text,
  attachments, provider, or session
- **THEN** the Gateway returns a bounded conflict response
- **AND** neither the original run nor a new run is changed

#### Scenario: Active run can be interrupted

- **WHEN** an authorized client requests interruption for an active run
- **THEN** the Gateway records a user-cancel reason, signals the running
  Agent, and exposes the interrupted terminal state through the run summary
  and event stream

### Requirement: Gateway exposes a bounded ordered run event stream

Run summaries, live events, and historical events SHALL include the effective
provider and model where available, using bounded machine fields. These fields
MUST remain stable after acceptance and MUST NOT contain credentials, endpoint
URLs, or raw provider responses.
Each run event SHALL have a monotonic per-run sequence. A subscription with a
cursor SHALL replay retained events after that cursor before live events,
report a history gap explicitly when the cursor cannot be satisfied, and
expose the durable terminal outcome so a client can stop reconnecting. Once a
run is terminal, publishing additional execution progress SHALL be rejected or
ignored.

#### Scenario: Live event identifies provider

- **WHEN** a run emits its start or model-turn event
- **THEN** the event exposes the snapshotted provider and model for safe UI
  presentation

#### Scenario: Reload preserves provider metadata

- **WHEN** a client retrieves a completed or failed run history
- **THEN** the run summary and relevant events retain the same provider and
  model metadata

#### Scenario: Tool trajectory is streamed

- **WHEN** an Agent run performs a model turn and invokes a tool
- **THEN** the live stream and later history expose ordered model, tool-call,
  and tool-result events with bounded tool names, call identifiers, arguments,
  and result summaries

#### Scenario: Visual observation is streamed safely

- **WHEN** a tool produces a valid generated visual observation
- **THEN** the stream emits a caption, media type, bounded dimensions or size
  metadata, and an opaque temporary observation ID without embedding raw image
  bytes or data URLs in the event JSON

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

- **WHEN** reasoning, tool arguments, tool results, or other event content
  exceeds its configured display limit
- **THEN** the Gateway sends a bounded representation with an explicit
  truncation marker and never sends credentials, raw provider responses, or
  unbounded data

#### Scenario: Terminal history is replayable after disconnect

- **WHEN** a client reconnects after a run has completed, failed, or been
  interrupted
- **THEN** the Gateway replays retained events and the authoritative terminal
  summary for that same run
- **AND** the stream closes without waiting for new execution progress

#### Scenario: Events after terminal state are not published

- **WHEN** a late model, tool, rendering, or review callback attempts to emit
  an event after terminalization
- **THEN** the Gateway ignores the callback for client-visible history
- **AND** the run sequence and terminal outcome remain unchanged

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

### Requirement: Gateway preserves generated-chart review lifecycle integrations

A Gateway-managed run that requires generated-chart review SHALL preserve the
operations needed to durably associate a candidate image with the exact
ChartSpec it represents, resolve those review inputs during review or recovery,
and propagate execution-gate updates to the owning run. Required review
integrations MUST NOT be silently omitted. A candidate SHALL remain unpublished
until its review inputs are persisted and the required review permits
publication. Missing runtime integration SHALL be distinguishable from an
actual candidate-storage failure, and genuine persistence failures SHALL
remain fail-closed.

#### Scenario: Default Gateway runtime prepares a reviewable candidate

- **WHEN** a Gateway-managed run renders a candidate whose policy requires review
- **THEN** the candidate image and the exact ChartSpec represented by it are durably associated with that candidate before review consumes them
- **AND** review gate updates are propagated to the owning run
- **AND** the candidate is not published until review permits publication

#### Scenario: Review inputs remain resolvable during recovery

- **WHEN** a Gateway-managed review resumes or restores a candidate
- **THEN** the runtime can resolve the same stored image and ChartSpec using bounded run, candidate, review, and digest references
- **AND** the restored review state continues to control the run's publication gate

#### Scenario: Missing integration is not reported as a storage write failure

- **WHEN** a Gateway runtime cannot provide a required candidate-review or gate integration
- **THEN** the run reports a bounded runtime-integration failure and does not misclassify the condition as `candidate_storage_failure`
- **AND** no candidate is published

#### Scenario: Actual candidate persistence failure remains fail-closed

- **WHEN** the configured candidate persistence operation is invoked but durable storage fails or rejects the candidate
- **THEN** the review reports a bounded candidate-storage failure
- **AND** the candidate remains unpublished

### Requirement: Gateway exposes safe run recovery and explicit resume

The Gateway SHALL expose bounded recovery metadata for a run, including
checkpoint availability, recovery phase, and a safe blocked reason when
applicable. It SHALL provide an authorized resume operation at
`/api/v1/sessions/{sessionId}/runs/{runId}/resume`. A valid resume request SHALL
use a new idempotency key, create a new child run from a recoverable
checkpoint, and preserve the parent terminal outcome. The Gateway SHALL reject
unavailable, expired, cross-session, or uncertain recovery with stable safe
errors.

#### Scenario: Resume returns a child run

- **WHEN** an authorized client resumes an interrupted run with an available
  checkpoint
- **THEN** the Gateway returns a new running run identity with a `resume`
  parent relationship
- **AND** it does not change the parent run's terminal summary or events

#### Scenario: Resume request is idempotent

- **WHEN** a client repeats the same resume request with the same idempotency
  key and parent checkpoint
- **THEN** the Gateway returns the original child run and current state
- **AND** it does not enqueue a second Agent continuation

#### Scenario: Recovery is blocked safely

- **WHEN** the parent has no valid checkpoint, an expired reference, or an
  uncertain in-flight operation without a replay-safe contract
- **THEN** the Gateway returns a bounded recovery-unavailable or
  recovery-blocked error with a stable reason
- **AND** it does not start a new Agent execution

#### Scenario: Resume authorization and lineage are enforced

- **WHEN** a client resumes a run from another session or submits a malformed
  checkpoint or idempotency identity
- **THEN** the Gateway rejects the request before execution
- **AND** it does not expose the other session's checkpoint or run data
