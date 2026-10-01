## MODIFIED Requirements

### Requirement: Public event projections are bounded and independent from execution facts
Figura SHALL persist Run-scoped, ordered lifecycle and progress events with an event sequence separate from record and tool-fact sequences. A `run_progress` event SHALL be appended atomically when a model response commits tool-call facts, a tool attempt starts, or a tool result commits. Its payload SHALL contain only the resulting checkpoint revision; the tool name, arguments, result, error, image bytes, and provider data SHALL remain in their authoritative records or tool facts. Event payloads SHALL use bounded allowlisted fields and SHALL exclude input text, provider credentials, raw endpoints, model response content, private continuation, and local storage paths. Event delivery through a network transport remains outside this capability.

#### Scenario: Read lifecycle events
- **WHEN** a caller reads the committed events for a Run
- **THEN** Figura returns events in event-sequence order using only the allowed lifecycle payload fields

#### Scenario: An execution commit fails
- **WHEN** a record or terminal transaction rolls back
- **THEN** no event describing that uncommitted action becomes visible

#### Scenario: Keep progress events independent from tool payloads
- **WHEN** a caller reads a `run_progress` event
- **THEN** the event contains no tool arguments, result, error, image, continuation, prompt, or other execution payload

#### Scenario: Commit a tool-fact progress marker atomically
- **WHEN** a model response with tool calls, a tool-attempt start, or a tool result commits
- **THEN** Figura appends one `run_progress` event in the same transaction as the corresponding tool facts and checkpoint revision

#### Scenario: Roll back a tool-fact transition
- **WHEN** a model-response, tool-attempt, or tool-result transaction fails before commit
- **THEN** neither its tool facts, checkpoint transition, nor corresponding `run_progress` event becomes visible
