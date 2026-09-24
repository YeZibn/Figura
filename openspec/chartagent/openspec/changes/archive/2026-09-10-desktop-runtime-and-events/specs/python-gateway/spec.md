## MODIFIED Requirements

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

#### Scenario: Run failure is isolated

- **WHEN** provider setup or Agent execution fails for a submitted message
- **THEN** the Gateway emits or returns a bounded failure, marks the run unsuccessful, and keeps prior completed session history readable

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
