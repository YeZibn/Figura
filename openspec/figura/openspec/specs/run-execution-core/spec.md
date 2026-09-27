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
Figura SHALL accept a bounded, nonempty text input, an optional ordered list of at most 16 unique attachment IDs, and an explicit allowlisted, locally configured provider/model pair. Every attachment ID SHALL identify a retained, validated image owned by the Run's Session. A successful creation SHALL atomically persist the Run, one immutable input record containing the text and ordered attachment IDs, an initial checkpoint pointing to the next model action, a creation idempotency mapping, and a bounded creation event. Provider network access SHALL NOT occur during this operation.

#### Scenario: Create a text-only Run
- **WHEN** a caller supplies valid text, an empty attachment list, an existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits a `running` Run whose first record contains the requested values, whose Run row contains the resolved provider/model pair, and whose checkpoint points to a model action after record sequence 1

#### Scenario: Create a Run with authorized images
- **WHEN** a caller supplies valid text and an ordered list of distinct retained image IDs owned by the existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits the ordered IDs in the immutable input record with the Run, checkpoint, idempotency mapping, and creation event in one transaction

#### Scenario: Reject unsupported input or provider selection
- **WHEN** a request has empty text, an invalid or unavailable attachment ID, a duplicate ID, more than 16 IDs, an unsupported or unavailable provider/model pair, or an unknown Session
- **THEN** Figura rejects creation before writing any Run, record, checkpoint, idempotency mapping, or event for that request

#### Scenario: Reject an attachment owned by another Session
- **WHEN** a request contains an attachment ID that belongs to a different Session
- **THEN** Figura rejects creation without disclosing the attachment's metadata and without writing any Run facts or events

### Requirement: Run creation is idempotent within its Session
Figura SHALL scope creation idempotency to the Session and a digest of the caller's key. Reusing a key with the same normalized text, ordered attachment IDs, and provider/model selection SHALL return the original Run; reusing it with different request content, attachment IDs, attachment order, or provider/model selection SHALL fail without creating another Run. Raw idempotency keys SHALL NOT be retained in durable facts or public events.

#### Scenario: Repeat the same create request
- **WHEN** a caller repeats a create request with the same Session, key, text, ordered attachment IDs, and provider/model selection
- **THEN** Figura returns the original Run and creates no new record or event

#### Scenario: Reuse a key for different input
- **WHEN** a caller reuses a Session-scoped key with changed text, attachment IDs or their order, or provider/model selection
- **THEN** Figura reports an idempotency conflict and leaves the existing Run unchanged

### Requirement: Runs within a Session are created sequentially
Figura SHALL allow at most one `running` Run per Session. Creating a new Run SHALL atomically reject a distinct request while that Session already has a running Run, without writing a Run or any of its facts. An idempotent replay that matches an existing Run SHALL return that Run, including while it is running. A new Run MAY be created after all prior Runs in the Session are terminal.

#### Scenario: Reject a second active Run in the same Session
- **WHEN** a caller submits a new, non-idempotent Run request while another Run in that Session has status `running`
- **THEN** Figura rejects the request without creating a Run, input record, checkpoint, idempotency mapping, or event

#### Scenario: Preserve idempotent replay of the active Run
- **WHEN** a caller repeats the original creation request with the same Session, idempotency key, and request content while its Run is still running
- **THEN** Figura returns the original Run and creates no additional Run or facts

#### Scenario: Create the next Run after the prior Run is terminal
- **WHEN** all existing Runs in a Session are completed, failed, or interrupted
- **THEN** Figura may create a new Run with the next Session ordinal

### Requirement: Execution facts and checkpoints advance together
Figura SHALL expose an internal commit boundary that appends only supported, bounded, versioned execution facts and advances the same Run's checkpoint atomically. Core record sequences and tool-execution fact sequences SHALL each be unique and increasing within a Run. A commit SHALL reject a stale expected checkpoint, an invalid record reference, an unsupported payload kind or version, or a terminal Run without partially advancing records, tool facts, checkpoint, or events. Core records SHALL support input, model responses, and final answers; a separate ordered tool-execution fact stream SHALL support tool-call intents, tool-attempt starts, and tool results. A model response SHALL be accepted only if any provider-private continuation it contains is valid, provider-scoped, within the continuation resource bound, and durably linked to that exact response. The response, private continuation, associated tool-call facts, and checkpoint SHALL be committed atomically. The state validator SHALL allow repeated model-response/tool-execution rounds only when every prior tool batch is fully resolved before the next model response, and SHALL verify that every non-null continuation reference resolves to the matching Run, response, provider, and supported format. Completion SHALL require a final text response with no pending or unresolved tool attempt.

#### Scenario: Commit a text-only model response without continuation
- **WHEN** a caller submits a bounded normalized model response with no tool calls or private continuation against the current model checkpoint
- **THEN** Figura appends the response as the next fact, stores no continuation, and advances the checkpoint to a final-answer action in the same commit

#### Scenario: Commit a text-only model response with continuation
- **WHEN** a caller submits a bounded normalized text response with valid provider-private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response and private continuation, links them, and advances the checkpoint to a final-answer action

#### Scenario: Commit a model response with tool calls
- **WHEN** a caller submits a bounded normalized response with ordered tool calls and an absent or valid provider-private continuation against the current model checkpoint
- **THEN** Figura atomically appends the response, its optional private continuation, its associated call intents, and advances both checkpoint cursors to the first tool action

#### Scenario: Commit against stale progress
- **WHEN** two callers attempt to commit against the same checkpoint version
- **THEN** at most one commit succeeds and the other leaves no partial fact, checkpoint, continuation, or event

#### Scenario: Reject an invalid or oversized continuation
- **WHEN** a response contains a provider-mismatched, unsupported, malformed, or oversized continuation, or its continuation reference does not resolve to the same Run and response
- **THEN** Figura rejects the whole response transition and retains the prior record prefix, tool-fact prefix, continuation set, and checkpoint

#### Scenario: Commit a later model response after a completed tool batch
- **WHEN** every tool call in the previous response has a committed result and the checkpoint points to a model action
- **THEN** Figura accepts the next model response and preserves the ordered history of prior model, continuation, and tool facts

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

### Requirement: Provider model actions are durably claimed before dispatch
Before an Agent sends a provider request for a Run whose checkpoint points to a model action, Figura SHALL atomically record one bounded provider-attempt identity and advance the checkpoint to that attempt. The claim SHALL compare the expected checkpoint revision and current action in the same transaction. A provider request SHALL NOT be dispatched unless its claim commits, and only one attempt SHALL be active for a Run at a time. Attempt metadata SHALL not contain the serialized prompt, tool schemas, credentials, raw endpoint, or provider response body.

#### Scenario: Claim the current model action
- **WHEN** the expected checkpoint revision is current and points to a model action
- **THEN** Figura records the attempt and advances the checkpoint to the matching provider-attempt action atomically

#### Scenario: Claim races with another executor
- **WHEN** two callers claim the same model action using the same checkpoint revision
- **THEN** at most one claim commits and the caller whose claim fails does not dispatch a provider request

#### Scenario: Attempt claim cannot be persisted
- **WHEN** storage fails before the provider-attempt claim commits
- **THEN** Figura leaves the prior checkpoint and facts unchanged and sends no provider request

### Requirement: Provider attempt outcomes are linked atomically to Run progress
A claimed provider attempt SHALL transition from `started` to exactly one terminal attempt outcome. A valid normalized response SHALL be linked to its attempt in the same transaction that appends the response, optional private continuation, associated tool-call facts, and next checkpoint. A known provider failure SHALL be recorded with bounded failure metadata and atomically fail the Run. An unknown provider outcome SHALL atomically mark the attempt unknown and fail the Run with terminal code `provider_outcome_unknown`. No terminal attempt outcome SHALL be replaced by another outcome.

#### Scenario: Commit a provider response
- **WHEN** the checkpoint points to a matching started provider attempt and a valid normalized response is committed
- **THEN** Figura links the attempt to the new response and commits the response, continuation, tool intents, and checkpoint in one transaction

#### Scenario: Record a known provider failure
- **WHEN** the provider returns a definitive failure for a started attempt
- **THEN** Figura records the bounded failure code, marks the attempt as a known failure, and commits the Run's failed state and terminal event atomically

#### Scenario: Record an unknown provider outcome
- **WHEN** the provider call fails without a definitive remote outcome
- **THEN** Figura marks the attempt as outcome unknown and commits a failed Run with terminal code `provider_outcome_unknown`, without resending the request

#### Scenario: Reject an attempt result for stale progress
- **WHEN** a response or failure refers to an attempt that is not the current started attempt at the expected checkpoint revision
- **THEN** Figura rejects the transition without partially changing the attempt, Run facts, checkpoint, or events

### Requirement: Recovery never resends a started provider attempt
Reading a Run SHALL remain side-effect free. After the previous per-Run execution owner is confirmed inactive, if a running Run's checkpoint references a provider attempt that remains `started`, recovery SHALL atomically mark that attempt outcome unknown and fail the Run with `provider_outcome_unknown`. Figura SHALL NOT infer that the request was never sent and SHALL NOT retry or select another provider/model.

#### Scenario: Recover a started attempt after process restart
- **WHEN** recovery acquires the Run's exclusive execution lock and finds a started provider attempt without a committed outcome
- **THEN** Figura records an unknown outcome and fails the Run without issuing a provider request

#### Scenario: Read an unresolved provider attempt
- **WHEN** a caller only reads a Run whose current checkpoint references a started provider attempt
- **THEN** Figura returns the persisted state without changing it or contacting the provider

#### Scenario: Preserve old Runs during schema migration
- **WHEN** a store containing schema-version-3 Runs is migrated to the provider-attempt schema
- **THEN** existing Run identities, records, continuations, tool facts, checkpoints, and terminal states remain readable without inventing provider attempts for already committed responses
