## MODIFIED Requirements

### Requirement: Gateway executes a text turn in a named session

The Gateway SHALL accept an optional bounded provider on synchronous and
asynchronous text-turn requests. It SHALL resolve the provider before
starting the Agent, snapshot the effective provider and model on the run, and
preserve the existing transcript and attachment behavior. Omitting provider
SHALL use the configured default provider. A selected provider that is
unavailable SHALL fail before Agent execution with a safe configuration
error. An asynchronous request MAY include an idempotency key and bounded
request fingerprint; repeated equivalent requests SHALL resolve to the same
run, while a conflicting reuse SHALL fail before execution. The Gateway
SHALL expose an authorized operation to interrupt an active run and SHALL
preserve its bounded terminal reason.

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
  client-supplied key, endpoint, model, or arbitrary provider body is ignored
  or rejected

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
  with a stable safe reason code, does not include credentials or raw
  exception text, marks the run unsuccessful, and keeps prior completed
  session history readable

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
URLs, or raw provider responses. Each run event SHALL have a monotonic
per-run sequence. A subscription with a cursor SHALL replay retained events
after that cursor before live events, report a history gap explicitly when the
cursor cannot be satisfied, and expose the durable terminal outcome so a
client can stop reconnecting. Once a run is terminal, publishing additional
execution progress SHALL be rejected or ignored.

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

