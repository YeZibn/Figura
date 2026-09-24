## MODIFIED Requirements

### Requirement: User can observe a live Agent run

The desktop workspace SHALL start a run through the backend boundary and
render its current state as connecting, running, reconnecting, completed,
failed, interrupted, or unavailable. While a run is active, the workspace
SHALL merge historical replay and live events into one ordered execution group
without replacing the primary conversation with raw protocol data. The
workspace SHALL retain the run identity and last applied sequence across an
event-stream interruption, SHALL distinguish reconnect from an explicit retry,
and SHALL treat the durable terminal summary as authoritative.

#### Scenario: User submits a Gateway-backed message

- **WHEN** the user sends non-empty text with zero or more selected attachment
  IDs in Gateway mode
- **THEN** the workspace immediately shows the user request and a running
  state, then consumes the associated run events until a terminal result

#### Scenario: Execution details arrive during a run

- **WHEN** the Gateway emits model, tool-call, or tool-result events
- **THEN** the workspace adds corresponding expandable execution details in
  order and keeps the main answer area scannable

#### Scenario: Run completes successfully

- **WHEN** the associated run emits a final answer
- **THEN** the workspace renders the Markdown assistant answer, marks the run
  completed, and refreshes the session summary without duplicating the user
  message or removing its execution group

#### Scenario: Run reconnects after an event-stream interruption

- **WHEN** the event connection becomes unavailable while the run is active
- **THEN** the workspace retains rendered events, enters an explicit
  reconnecting state, requests missing events after the last applied sequence
  when possible, and resumes the same run
- **AND** it reports an explicit history-gap state if replay is unavailable

#### Scenario: Run fails or Gateway becomes unavailable

- **WHEN** the run emits a bounded failure or the event connection becomes
  unavailable after reconnect attempts are exhausted
- **THEN** the workspace marks the run as failed or unavailable, shows
  Simplified Chinese recovery feedback, and preserves all prior events and
  completed conversation content

#### Scenario: Interrupted run is rendered as interrupted

- **WHEN** the run summary or event history reports a user, Gateway, provider,
  worker, or retention interruption reason
- **THEN** the workspace marks the run interrupted, shows the bounded reason in
  Simplified Chinese, and does not present an unfinished answer as completed

#### Scenario: Reconnect does not create duplicate work

- **WHEN** the workspace reconnects after losing an acknowledgement or SSE
  connection
- **THEN** it resumes the existing run by identity and sequence
- **AND** it does not submit another user message or Agent execution

#### Scenario: Explicit retry creates a new run

- **WHEN** the user chooses retry for a failed or interrupted run
- **THEN** the workspace starts a new run with a new identity and displays its
  bounded retry relationship to the prior run
- **AND** the prior run's events and terminal state remain inspectable

### Requirement: Backend boundary supports live events in mock and Gateway modes

The client boundary SHALL expose equivalent run and event contracts for mock
and Gateway adapters. Mock mode SHALL simulate a bounded ordered event
sequence without network access, while Gateway mode SHALL use the local event
stream and SHALL NOT silently fall back to mock events. The run submission
contract SHALL allow the client to provide an idempotency key, and the Gateway
adapter SHALL preserve the returned run identity on an equivalent repeated
submission.

#### Scenario: Mock mode exercises the live-run UI

- **WHEN** the client runs in mock mode and the user submits a message
- **THEN** the UI receives simulated running, execution-detail, and terminal
  events through the same boundary used by Gateway mode

#### Scenario: Gateway mode uses real events

- **WHEN** the client runs in Gateway mode and the local Gateway is ready
- **THEN** run state, execution details, visual observations, and final answer
  are driven by the Gateway contract rather than fabricated client data

#### Scenario: Gateway mode is not ready

- **WHEN** Gateway mode is selected but the local runtime is unavailable
- **THEN** the client shows the unavailable state and does not silently switch
  to mock mode

#### Scenario: Equivalent repeated submission preserves identity

- **WHEN** the adapter repeats an asynchronous submission with the same
  idempotency key and equivalent request data
- **THEN** it exposes the original run identity and state to the workspace
- **AND** it does not synthesize a second run

