## MODIFIED Requirements

### Requirement: Run history and SSE expose replayable lifecycle events
The Gateway SHALL provide a Session-scoped Run summary, a history read after an optional event sequence, and an SSE stream that replays persisted events after a requested sequence before following new events. Durable event IDs SHALL preserve the Run ID and durable event sequence. The allowlisted `run_progress` marker SHALL expose the committed checkpoint revision and, when applicable, bounded Provider request purpose, attempt identity, and phase. It SHALL NOT contain input text, reasoning, tool arguments/results, continuation, credentials, raw endpoints, local paths, or raw error bodies. Terminal events SHALL close the stream after delivery; durable progress events SHALL keep it open.

The same SSE connection MAY deliver transient `assistant_delta` events for the active Run. Such events SHALL have no durable event ID and SHALL NOT advance the durable event cursor. Each event SHALL contain only the Session-owned Run ID, current attempt ID, a monotonically increasing delta sequence within that attempt, and assistant-visible text. Deltas SHALL NOT be stored as Run events and SHALL NOT include reasoning or tool-call fragments. A new attempt SHALL identify a new delta sequence scope so clients can discard partial text from an interrupted attempt.

#### Scenario: Catch up after reconnecting to a Run
- **WHEN** a browser reconnects with the last observed durable event sequence
- **THEN** the Gateway delivers every later persisted lifecycle event in sequence order without duplicating earlier events, while transient deltas do not alter that cursor

#### Scenario: Recover history when events are written before subscription
- **WHEN** the Run creation or terminal event is already persisted before the browser opens SSE
- **THEN** the history read and stream replay deliver those events according to their durable sequence

#### Scenario: Deliver a terminal lifecycle event
- **WHEN** a Run completes, fails, or is interrupted
- **THEN** the stream delivers the corresponding terminal event with bounded status metadata and then closes

#### Scenario: Reject cross-Session Run event access
- **WHEN** the browser reads history or opens an event stream for a Run through a Session that does not own it
- **THEN** the Gateway rejects the request without returning the Run or its events

#### Scenario: Refresh timeline after a progress marker
- **WHEN** the browser receives a `run_progress` event
- **THEN** it can read the corresponding committed tool-fact snapshot through the Session-scoped timeline route, while the SSE payload itself remains free of tool details

#### Scenario: Deliver transient assistant text
- **WHEN** the current Provider attempt emits assistant-visible text
- **THEN** the Gateway delivers ordered transient deltas without persisting them or changing the durable event cursor

#### Scenario: Start a replacement attempt
- **WHEN** a retry begins after an interrupted attempt emitted partial text
- **THEN** the Gateway identifies the new attempt so the client can discard the previous attempt's transient text

#### Scenario: Reconnect during an active stream
- **WHEN** a browser reconnects after missing transient deltas
- **THEN** the Gateway resumes durable lifecycle replay, sends only newly available transient deltas, and leaves canonical history unchanged until the complete response commits
