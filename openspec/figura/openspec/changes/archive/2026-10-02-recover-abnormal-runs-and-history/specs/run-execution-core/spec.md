## MODIFIED Requirements

### Requirement: Runs within a Session are created sequentially
Figura SHALL allow at most one `running` Run per Session. Creating a new Run SHALL atomically reject a distinct request while that Session already has a running Run, without writing a Run or any of its facts. An idempotent replay that matches an existing Run SHALL return that Run, including while it is running. A distinct new Run SHALL be permitted only after all prior Runs are terminal and their execution owners have released ownership. A terminal status alone SHALL NOT authorize racing with an executor still releasing ownership.

#### Scenario: Reject a second active Run in the same Session
- **WHEN** a caller submits a new, non-idempotent Run request while another Run in that Session has status `running`
- **THEN** Figura rejects the request without creating a Run, input record, checkpoint, idempotency mapping, or event

#### Scenario: Preserve idempotent replay of the active Run
- **WHEN** a caller repeats the original creation request with the same Session, idempotency key, and request content while its Run is still running
- **THEN** Figura returns the original Run and creates no additional Run or facts

#### Scenario: Create the next Run after the prior Run is terminal
- **WHEN** all existing Runs in a Session are completed, failed, or interrupted
- **THEN** Figura may create a new Run with the next Session ordinal

#### Scenario: Wait for terminal execution ownership release
- **WHEN** a previous Run is terminal but its execution owner has not released ownership
- **THEN** a distinct creation is rejected with a bounded conflict while matching creation idempotency still returns the existing Run

### Requirement: Public event projections are bounded and independent from execution facts
Figura SHALL persist Run-scoped, ordered lifecycle and progress events with an event sequence separate from record and tool-fact sequences. A `run_progress` event SHALL be appended atomically when a model response commits tool-call facts, a tool attempt starts, or a tool result commits, and when the first stop request is accepted. Its payload SHALL contain only the resulting checkpoint revision; the tool name, arguments, result, error, image bytes, and provider data SHALL remain in their authoritative records or tool facts. Event payloads SHALL use bounded allowlisted fields and SHALL exclude input text, provider credentials, raw endpoints, model response content, private continuation, and local storage paths. Event delivery through a network transport remains outside this capability.

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
- **THEN** Figura appends one `run_progress` event in the same transaction as the corresponding execution transition and checkpoint revision

#### Scenario: Roll back a tool-fact transition
- **WHEN** a model-response, tool-attempt, or tool-result transaction fails before commit
- **THEN** neither its tool facts, checkpoint transition, nor corresponding `run_progress` event becomes visible

#### Scenario: Notify stop acceptance without changing execution revision
- **WHEN** the first stop request is committed for a running Run
- **THEN** one progress event containing the current checkpoint revision commits with the request while execution cursors and revision remain unchanged; repeated revision values are valid control notifications

### Requirement: Run terminal transitions preserve a single authoritative outcome
Figura SHALL allow a `running` Run to become `completed`, `failed`, or `interrupted` through an atomic terminal commit. Completion SHALL reference a committed final-answer record associated with the same Run and a committed text-only model response; failed and interrupted outcomes SHALL carry bounded safe reason metadata. A terminal Run SHALL NOT be reopened or changed to another terminal outcome in place.

A pending user stop SHALL be finalized as interrupted only through safe execution-owner coordination. If a stop request commits before final completion or failure, terminal arbitration SHALL preserve actual outcomes of already claimed attempts and select interrupted. If an outcome is already terminal, a later stop SHALL return it unchanged. Terminal commits SHALL retain an assessable checkpoint, reject later execution commits, and append exactly one last terminal event.

#### Scenario: Complete a Run with a committed final answer
- **WHEN** a final-answer record refers to a valid committed response for the Run and the current checkpoint permits finalization
- **THEN** Figura commits the final record, completed status, final-record reference, cleared next action, and terminal event together

#### Scenario: Fail or interrupt a Run
- **WHEN** the coordinator commits failure or interruption for a running Run
- **THEN** Figura persists exactly one terminal state and safe reason, while retaining the last committed checkpoint for later recovery assessment

#### Scenario: Attempt a second terminal transition
- **WHEN** a caller attempts to change a completed, failed, or interrupted Run
- **THEN** Figura rejects the transition without appending a new execution fact or terminal event

#### Scenario: Stop during an unfinished Provider attempt
- **WHEN** a running Run has an accepted stop request and a started Provider attempt whose owner has exited
- **THEN** one transaction marks the attempt outcome unknown, advances the terminal revision, retains factual progress, and writes interrupted with one terminal event

#### Scenario: Stop races with a known Provider failure
- **WHEN** a stop request commits before the known failure outcome of an already started Provider attempt
- **THEN** the actual known failure is persisted but the Run converges on interrupted without a second terminal transition

#### Scenario: Storage failure during stop closure
- **WHEN** the stop-closure transaction cannot commit
- **THEN** neither a partial attempt outcome nor a terminal status/event is published and the Session is not declared available


### Requirement: Provider attempt outcomes are linked atomically to Run progress
A claimed provider attempt SHALL transition from `started` to exactly one terminal attempt outcome. A valid normalized response SHALL be linked to its attempt in the same transaction that appends the response, optional private continuation, associated tool-call facts, and next checkpoint. A known provider failure SHALL be recorded with bounded failure metadata and atomically fail the Run unless a stop request has already committed, in which case it SHALL atomically interrupt the Run while preserving the known failure. An unknown provider outcome SHALL atomically mark the attempt unknown and fail the Run with terminal code `provider_outcome_unknown` unless a stop request has already committed, in which case it SHALL atomically interrupt the Run while preserving the unknown attempt outcome. No terminal attempt outcome SHALL be replaced by another outcome.

#### Scenario: Commit a provider response
- **WHEN** the checkpoint points to a matching started provider attempt and a valid normalized response is committed
- **THEN** Figura links the attempt to the new response and commits the response, continuation, tool intents, and checkpoint in one transaction

#### Scenario: Record a known provider failure
- **WHEN** the provider returns a definitive failure for a started attempt with no accepted stop request
- **THEN** Figura records the bounded failure code, marks the attempt as a known failure, and commits the Run's failed state and terminal event atomically

#### Scenario: Record an unknown provider outcome
- **WHEN** the provider call fails without a definitive remote outcome and no stop request has been accepted
- **THEN** Figura marks the attempt as outcome unknown and commits a failed Run with terminal code `provider_outcome_unknown`, without resending the request

#### Scenario: Reject an attempt result for stale progress
- **WHEN** a response or failure refers to an attempt that is not the current started attempt at the expected checkpoint revision
- **THEN** Figura rejects the transition without partially changing the attempt, Run facts, checkpoint, or events

### Requirement: Recovery never resends a started provider attempt
Reading a Run SHALL remain side-effect free. After the previous per-Run execution owner is confirmed inactive, if a running Run's checkpoint references a provider attempt that remains `started`, recovery SHALL atomically mark that attempt outcome unknown and fail the Run with `provider_outcome_unknown`, or interrupt it when a durable stop request has already been accepted. Figura SHALL NOT infer that the request was never sent and SHALL NOT retry or select another provider/model.

#### Scenario: Recover a started attempt after process restart
- **WHEN** recovery acquires the Run's exclusive execution lock and finds a started provider attempt without a committed outcome or accepted stop request
- **THEN** Figura records an unknown outcome and fails the Run without issuing a provider request

#### Scenario: Read an unresolved provider attempt
- **WHEN** a caller only reads a Run whose current checkpoint references a started provider attempt
- **THEN** Figura returns the persisted state without changing it or contacting the provider

#### Scenario: Preserve old Runs during schema migration
- **WHEN** a store containing schema-version-3 Runs is migrated to the provider-attempt schema
- **THEN** existing Run identities, records, continuations, tool facts, checkpoints, and terminal states remain readable without inventing provider attempts for already committed responses

### Requirement: A terminal Session and its Runtime facts can be purged as one aggregate
Runtime SHALL allow permanent deletion of an existing Session only when none of its Runs is `running` and no execution owner remains active. A successful aggregate deletion SHALL remove the Session and all Runtime-owned data for its Runs, including execution records, tool facts, checkpoints, events, Provider attempts, continuations, stop requests, and idempotency mappings, in one SQLite transaction. While a Session exists, individual immutable execution facts SHALL remain non-deletable; deletion authorization SHALL apply only to the complete Session aggregate. If the transaction fails, no Runtime-owned row in the aggregate SHALL be removed.

#### Scenario: Purge a terminal Session
- **WHEN** the deletion operation targets a Session whose Runs are all terminal and whose execution ownership has been released
- **THEN** the Session and every Runtime-owned row belonging to those Runs are removed together

#### Scenario: Reject a Session containing a running Run
- **WHEN** the deletion operation targets a Session with a `running` Run
- **THEN** Runtime rejects the operation and retains the Session and all Runtime facts

#### Scenario: Preserve fact immutability outside aggregate deletion
- **WHEN** an operation attempts to delete an individual Run fact without deleting its owning Session aggregate
- **THEN** Runtime rejects the deletion and retains the fact

#### Scenario: Roll back a failed aggregate purge
- **WHEN** a database failure occurs before the Session deletion transaction commits
- **THEN** the transaction leaves the Session, Runs, and their Runtime facts intact

## ADDED Requirements

### Requirement: Stop requests are durable idempotent controls
Figura SHALL accept a stop request only for a running Run in its owning Session and persist at most one request per Run with an opaque request ID, UTC request time, and fixed user-requested reason. Repetition SHALL return the original request without appending another event. Acceptance SHALL NOT modify immutable input, execution facts, execution sequence cursors, or checkpoint revision. A terminal Run SHALL return its existing outcome without adding a request. The request SHALL survive restart and SHALL be removed with the Session aggregate.

#### Scenario: Repeat a stop request
- **WHEN** a caller stops the same running Run twice
- **THEN** both responses identify the same request and only the first transaction writes a request and progress notification

#### Scenario: Recover a stop after restart
- **WHEN** the store is reopened after stop acceptance but before closure
- **THEN** the same request is reconstructed with the Run snapshot and takes precedence over starting or replaying work

#### Scenario: Reject cross-Session stop
- **WHEN** a caller uses another Session identity to stop a Run
- **THEN** the request is rejected without disclosing or changing the Run

### Requirement: Stop and action-start arbitration is atomic
Every initial or replayed tool-attempt claim, Provider-attempt claim, and final-completion transaction SHALL check for an accepted stop request. A request that commits first SHALL prevent the new claim or completion. An attempt that is claimed first SHALL be allowed to dispatch and persist its genuine outcome, after which execution SHALL stop before another action. Preparation without a claim SHALL NOT count as a started action. Accepting stop SHALL NOT invalidate an in-flight result revision.

#### Scenario: Stop wins before claim
- **WHEN** stop acceptance commits before a prepared Provider request is claimed
- **THEN** no Provider attempt or network dispatch occurs and coordination proceeds to interruption

#### Scenario: Claim wins before stop
- **WHEN** a tool attempt is claimed before stop acceptance
- **THEN** the tool may return and commit its real result but no next tool or Provider action starts

#### Scenario: Completion wins before stop
- **WHEN** completion commits before a concurrent stop request
- **THEN** stop returns completed unchanged without a new request or event

### Requirement: Execution ownership gates takeover and mutation
Figura SHALL establish exclusive cross-process ownership for the full execution task and separately protect action execution and recovery. Takeover SHALL require exclusive ownership and a fresh validated state. Queue bookkeeping, timeouts, page disconnection, and old timestamps SHALL NOT prove prior execution inactivity. Reads SHALL NOT perform takeover. Terminal Runs SHALL accept no new execution or source writes; Session deletion SHALL wait for relevant execution ownership release.

#### Scenario: Two executors contend
- **WHEN** two processes attempt to advance the same Run
- **THEN** only one advances facts or effects and the other returns a bounded unavailable result without failing the Run

#### Scenario: Owner remains active
- **WHEN** a running tool is slow and a stop request has been accepted
- **THEN** the Run remains stopping/running until cooperative return or confirmed owner exit, without premature interruption or deletion
