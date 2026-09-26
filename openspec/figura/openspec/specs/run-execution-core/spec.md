## Purpose

Defines Figura's durable Run boundary so downstream execution code can create an isolated Run, commit ordered facts with its checkpoint, and reconstruct only committed progress after a process restart.

## Requirements

### Requirement: Sessions and Runs have isolated durable identities
Figura SHALL persist Sessions and their Runs under opaque identities. Each Run SHALL belong to exactly one Session and receive a monotonically increasing ordinal within that Session. A Run SHALL retain the explicitly resolved provider/model pair for its lifetime, and a Run belonging to another Session SHALL NOT be returned through a Session-scoped read.

#### Scenario: Create a Run in a Session
- **WHEN** an internal caller creates a Run for an existing Session with an allowed, locally available provider/model pair
- **THEN** Figura assigns a new opaque Run ID and the next ordinal for that Session, and persists that provider/model pair on the Run

#### Scenario: Session-scoped read uses another Session's Run ID
- **WHEN** a caller requests a Run using a Session ID that does not own it
- **THEN** Figura rejects the read without returning the Run or its records

### Requirement: Run creation commits immutable input and initial progress atomically
Figura SHALL accept only a bounded, nonempty text input and an explicit allowlisted, locally configured provider/model pair in this change. Nonempty attachment references SHALL be rejected until attachment authorization exists. A successful creation SHALL atomically persist the Run, one immutable input record, an initial checkpoint pointing to the next model action, a creation idempotency mapping, and a bounded creation event. Provider network access SHALL NOT occur during this operation.

#### Scenario: Create a text-only Run
- **WHEN** a caller supplies valid text, an empty attachment list, an existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits a `running` Run whose first record contains the requested values, whose Run row contains the resolved provider/model pair, and whose checkpoint points to a model action after record sequence 1

#### Scenario: Reject unsupported input or provider selection
- **WHEN** a request has nonempty attachment references, empty text, an unsupported or unavailable provider/model pair, or an unknown Session
- **THEN** Figura rejects creation before writing any Run, record, checkpoint, idempotency mapping, or event for that request

### Requirement: Run creation is idempotent within its Session
Figura SHALL scope creation idempotency to the Session and a digest of the caller's key. Reusing a key with the same normalized request SHALL return the original Run; reusing it with different request content SHALL fail without creating another Run. Raw idempotency keys SHALL NOT be retained in durable facts or public events.

#### Scenario: Repeat the same create request
- **WHEN** a caller repeats a create request with the same Session, key, and normalized input
- **THEN** Figura returns the original Run and creates no new record or event

#### Scenario: Reuse a key for different input
- **WHEN** a caller reuses a Session-scoped key with changed text or provider/model selection
- **THEN** Figura reports an idempotency conflict and leaves the existing Run unchanged

### Requirement: Execution facts and checkpoints advance together
Figura SHALL expose an internal commit boundary that appends only supported, bounded, versioned execution facts and advances the same Run's checkpoint atomically. Core record sequences and tool-execution fact sequences SHALL each be unique and increasing within a Run. A commit SHALL reject a stale expected checkpoint, an invalid record reference, an unsupported payload kind or version, or a terminal Run without partially advancing records, tool facts, checkpoint, or events. Core records SHALL support input, model responses, and final answers; a separate ordered tool-execution fact stream SHALL support tool-call intents, tool-attempt starts, and tool results. A response containing tool calls SHALL be accepted only when it has no provider-private continuation. The state validator SHALL allow repeated model-response/tool-execution rounds only when every prior tool batch is fully resolved before the next model response. Completion SHALL require a final text response with no pending or unresolved tool attempt.

#### Scenario: Commit a text-only model response
- **WHEN** a caller submits a bounded normalized model response with no tool calls or private continuation against the current model checkpoint
- **THEN** Figura appends the response as the next fact and advances the checkpoint to a final-answer action in the same commit

#### Scenario: Commit a model response with tool calls
- **WHEN** a caller submits a bounded normalized response with ordered tool calls and no private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response to the core record stream, its associated call intents to the tool-execution fact stream, and advances both checkpoint cursors to the first tool action

#### Scenario: Commit against stale progress
- **WHEN** two callers attempt to commit against the same checkpoint version
- **THEN** at most one commit succeeds and the other leaves no partial fact, checkpoint, or event

#### Scenario: Response contains unsupported private continuation
- **WHEN** a model response includes provider-private continuation
- **THEN** Figura rejects the commit and retains the prior checkpoint and record prefix

#### Scenario: Commit a later model response after a completed tool batch
- **WHEN** every tool call in the previous response has a committed result and the checkpoint points to a model action
- **THEN** Figura accepts the next model response and preserves the ordered history of prior model and tool facts

#### Scenario: Attempt completion with unresolved tool work
- **WHEN** a caller attempts to finalize a Run while any tool call is pending or has an unresolved attempt
- **THEN** Figura rejects completion without appending a final-answer fact or changing the Run's terminal state

### Requirement: Run terminal transitions preserve a single authoritative outcome
Figura SHALL allow a `running` Run to become `completed`, `failed`, or `interrupted` through an atomic terminal commit. Completion SHALL reference a committed final-answer record associated with the same Run and a committed text-only model response; failed and interrupted outcomes SHALL carry bounded safe reason metadata. A terminal Run SHALL NOT be reopened or changed to another terminal outcome in place.

#### Scenario: Complete a Run with a committed final answer
- **WHEN** a final-answer record refers to a valid committed response for the Run and the current checkpoint permits finalization
- **THEN** Figura commits the final record, completed status, final-record reference, cleared next action, and terminal event together

#### Scenario: Fail or interrupt a Run
- **WHEN** the coordinator commits failure or interruption for a running Run
- **THEN** Figura persists exactly one terminal state and safe reason, while retaining the last committed checkpoint for later recovery assessment

#### Scenario: Attempt a second terminal transition
- **WHEN** a caller attempts to change a completed, failed, or interrupted Run
- **THEN** Figura rejects the transition without appending a new execution fact or terminal event

### Requirement: Committed progress is readable without replaying work
Figura SHALL reconstruct a Run from its stored Run row, committed record prefix, and checkpoint after restart. Reads SHALL fail closed on unsupported data versions or inconsistent references. Reading recovery state SHALL NOT trigger a provider request, tool invocation, automatic retry, or resume child creation.

#### Scenario: Read after process restart
- **WHEN** a process opens the Figura store after a Run creation or execution commit
- **THEN** it reads the same Run identity, ordered committed records, and matching checkpoint without reissuing the external action

#### Scenario: Stored state is inconsistent
- **WHEN** a checkpoint points beyond the committed record prefix or a required referenced record is absent
- **THEN** Figura reports a bounded integrity failure and does not synthesize missing progress

### Requirement: Public event projections are bounded and independent from execution facts
Figura SHALL persist Run-scoped, ordered lifecycle events with an event sequence separate from record sequence. Event payloads SHALL use bounded allowlisted fields and SHALL exclude input text, provider credentials, raw endpoints, model response content, private continuation, and local storage paths. Event delivery through a network transport is outside this change.

#### Scenario: Read lifecycle events
- **WHEN** a caller reads the committed events for a Run
- **THEN** Figura returns events in event-sequence order using only the allowed lifecycle payload fields

#### Scenario: An execution commit fails
- **WHEN** a record or terminal transaction rolls back
- **THEN** no event describing that uncommitted action becomes visible
