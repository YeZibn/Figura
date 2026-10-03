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
Figura SHALL accept a bounded, nonempty text input, an optional ordered list of unique attachment IDs within the shared complete-input payload guard, and an explicit allowlisted, locally configured provider/model pair. Every attachment ID SHALL identify a retained, validated image owned by the Run's Session. A successful creation SHALL atomically persist the Run, one immutable input record containing the text and ordered attachment IDs, an initial checkpoint pointing to the next model action, a creation idempotency mapping, and a bounded creation event. Provider network access SHALL NOT occur during this operation.

#### Scenario: Create a text-only Run
- **WHEN** a caller supplies valid text, an empty attachment list, an existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits a `running` Run whose first record contains the requested values, whose Run row contains the resolved provider/model pair, and whose checkpoint points to a model action after record sequence 1

#### Scenario: Create a Run with authorized images
- **WHEN** a caller supplies valid text and an ordered list of distinct retained image IDs owned by the existing Session, an explicit available provider/model pair, and an idempotency key
- **THEN** Figura commits the ordered IDs in the immutable input record with the Run, checkpoint, idempotency mapping, and creation event in one transaction

#### Scenario: Reject unsupported input or provider selection
- **WHEN** a request has empty text, an invalid or unavailable attachment ID, a duplicate ID, a complete input exceeding the shared payload guard, an unsupported or unavailable provider/model pair, or an unknown Session
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

### Requirement: Committed progress is readable without replaying work
Figura SHALL reconstruct a Run from its stored Run row, committed record prefix, and checkpoint after restart. Reads SHALL fail closed on unsupported data versions or inconsistent references. Reading recovery state SHALL NOT trigger a provider request, tool invocation, automatic retry, or resume child creation.

#### Scenario: Read after process restart
- **WHEN** a process opens the Figura store after a Run creation or execution commit
- **THEN** it reads the same Run identity, ordered committed records, and matching checkpoint without reissuing the external action

#### Scenario: Stored state is inconsistent
- **WHEN** a checkpoint points beyond the committed record prefix or a required referenced record is absent
- **THEN** Figura reports a bounded integrity failure and does not synthesize missing progress

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

### Requirement: Provider model actions are durably claimed before dispatch
Before an Agent sends a provider request for a Run whose checkpoint points to a model action, Figura SHALL complete local request validation and Provider-specific payload preparation. If preparation succeeds, Figura SHALL atomically record an immutable private logical-request binding and its first provider-attempt identity, or claim a due next attempt against the existing exact binding and advance the checkpoint to that attempt, comparing the expected checkpoint revision and current action in the same transaction. A provider request SHALL NOT be dispatched unless its claim commits, and only one attempt SHALL be active for a Run at a time. If local preparation fails, Figura SHALL fail the Run through its existing bounded terminal state without claiming a Provider attempt or dispatching a request. For a known local Provider preparation rejection, the existing Run terminal message SHALL contain a bounded, allowlisted safe explanation of the rejection and the terminal code SHALL remain `execution_failed`. Unknown exceptions SHALL use the generic safe failure message. The explanation SHALL exclude continuation content and references, prompts, credentials, endpoints, raw SDK errors, and response bodies, and SHALL be retained on later Run reads through the existing public terminal-message projection. No additional execution fact or event payload field SHALL be created for preparation failures. Neither binding nor attempt metadata SHALL contain the serialized prompt, tool schemas, credentials, raw endpoint, or provider response body.

Retry claims SHALL preserve the original request prefix and binding, enforce the per-logical-request four-attempt allowance, and check the due time and accepted stop. The Run-wide attempt sequence SHALL have no eight-attempt ceiling. Legacy direct claims without reproducible bindings SHALL remain readable but SHALL not permit unknown-outcome automatic replacement.

#### Scenario: Prepare and claim the current model action
- **WHEN** local request preparation succeeds and the expected checkpoint revision is current and points to a model action
- **THEN** Figura records the attempt and advances the checkpoint to the matching provider-attempt action atomically before dispatch

#### Scenario: Reject a locally incompatible request before attempt claim
- **WHEN** local Provider request validation or payload preparation rejects the model action
- **THEN** Figura commits the existing bounded Run failure state, creates no Provider attempt, and sends no Provider request

#### Scenario: Claim races with another executor
- **WHEN** two callers claim the same model action using the same checkpoint revision
- **THEN** at most one claim commits and the caller whose claim fails does not dispatch a provider request

#### Scenario: Attempt claim cannot be persisted
- **WHEN** storage fails before the provider-attempt claim commits
- **THEN** Figura leaves the prior checkpoint and facts unchanged and sends no provider request

#### Scenario: Explain a missing DeepSeek continuation locally
- **WHEN** local preparation rejects a DeepSeek tool-history request because a required continuation is genuinely absent
- **THEN** the failed Run's existing terminal message explains the missing required history safely within 256 UTF-8 bytes
- **AND** no Provider attempt or network request is created

#### Scenario: Suppress unsafe unexpected preparation errors
- **WHEN** local preparation raises an unrecognized exception containing internal or sensitive details
- **THEN** the Run uses the generic safe terminal message without persisting or projecting those details

#### Scenario: Claim a due replacement
- **WHEN** the checkpoint references a due retry, its prior attempt is closed, the original binding matches, stop is absent and allowance remains
- **THEN** one new attempt identity commits atomically with the next checkpoint before any replacement dispatch

#### Scenario: Reject a fifth physical attempt
- **WHEN** a logical request already has four claimed attempts
- **THEN** no execution caller can obtain a fifth claim even after reopening the store

### Requirement: Provider attempt outcomes are linked atomically to Run progress
A claimed provider attempt SHALL transition from `started` to exactly one terminal attempt outcome. A valid normalized response SHALL be linked to its attempt in the same transaction that appends the response, optional private continuation, associated tool-call facts, and next checkpoint. A known failure SHALL be recorded with bounded classification metadata and atomically move to a persisted retry checkpoint only when eligible and allowance remains; otherwise it SHALL fail the Run. An already accepted stop SHALL interrupt instead while preserving the genuine failure. An unknown outcome SHALL atomically mark the attempt unknown and schedule a replacement only under the generation-only retry contract; otherwise it SHALL fail with `provider_outcome_unknown`. An already accepted stop SHALL interrupt instead while preserving the unknown outcome. No terminal attempt outcome SHALL be replaced by another outcome.

At most one accepted response SHALL belong to a logical request. Previous known failures and unknown attempts SHALL remain immutable and valid before a later accepted response; their presence SHALL not corrupt history or synthesize messages. Retry scheduling SHALL publish only existing safe progress fields in the same transaction.

#### Scenario: Commit a provider response
- **WHEN** the checkpoint points to a matching started provider attempt and a valid normalized response is committed
- **THEN** Figura links the attempt to the new response and commits the response, continuation, tool intents, and checkpoint in one transaction

#### Scenario: Record a known provider failure
- **WHEN** the provider returns a definitive failure for a started attempt with no accepted stop request
- **THEN** Figura records the bounded failure code, marks the attempt as a known failure, and atomically schedules a durable eligible retry or commits the Run failure when retry is ineligible or exhausted

#### Scenario: Record an unknown provider outcome
- **WHEN** the provider call fails without a definitive remote outcome and no stop request has been accepted
- **THEN** Figura marks the attempt as outcome unknown and atomically schedules only an eligible guarded replacement, or fails with `provider_outcome_unknown` without dispatch when ineligible or exhausted

#### Scenario: Reject an attempt result for stale progress
- **WHEN** a response or failure refers to an attempt that is not the current started attempt at the expected checkpoint revision
- **THEN** Figura rejects the transition without partially changing the attempt, Run facts, checkpoint, or events

#### Scenario: Commit success after an unknown attempt
- **WHEN** an eligible replacement returns a valid response while an earlier attempt for the same logical request is unknown
- **THEN** Figura commits one response and its complete transition, retains the old unknown fact, and exposes no duplicate tool intent or history message

### Requirement: Recovery closes orphaned provider attempts before eligible replacement
Reading a Run SHALL remain side-effect free. After the previous per-Run execution owner is confirmed inactive, if a running Run's checkpoint references a provider attempt that remains `started`, recovery SHALL atomically mark that attempt unknown and apply the durable generation-only replacement contract if a reproducible binding and allowance exist. It SHALL otherwise fail with `provider_outcome_unknown`, or interrupt when stop has been accepted. Figura SHALL NOT infer no-send, redispatch the same started attempt identity, reset allowance or select another Provider/model.

#### Scenario: Recover a started attempt after process restart
- **WHEN** recovery acquires the Run's exclusive execution lock and finds a started provider attempt without a committed outcome or accepted stop request
- **THEN** Figura records the unknown outcome and either schedules a guarded due replacement or fails when ineligible, without dispatch as part of the recovery-closing transaction

#### Scenario: Read an unresolved provider attempt
- **WHEN** a caller only reads a Run whose current checkpoint references a started provider attempt
- **THEN** Figura returns the persisted state without changing it or contacting the provider

#### Scenario: Preserve old Runs during schema migration
- **WHEN** a store containing schema-version-3 Runs is migrated to the provider-attempt schema
- **THEN** existing Run identities, records, continuations, tool facts, checkpoints, and terminal states remain readable without inventing provider attempts for already committed responses

#### Scenario: Recover a legacy attempt without binding
- **WHEN** an orphaned historical started attempt has no exact reproducible request binding
- **THEN** Figura records unknown and fails or honors stop without guessing a request or fabricating a binding

### Requirement: A terminal Session and its Runtime facts can be purged as one aggregate
Runtime SHALL allow permanent deletion of an existing Session only when none of its Runs is `running` and no execution owner remains active. A successful aggregate deletion SHALL remove the Session and all Runtime-owned data for its Runs, including execution records, tool facts, checkpoints, events, Provider request bindings, Provider attempts, continuations, stop requests, and idempotency mappings, in one SQLite transaction. While a Session exists, individual immutable execution facts SHALL remain non-deletable; deletion authorization SHALL apply only to the complete Session aggregate. If the transaction fails, no Runtime-owned row in the aggregate SHALL be removed.

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
Figura SHALL establish exclusive cross-process ownership for each execution task or action slice, including every active handler, and SHALL separately protect action execution and recovery. Takeover SHALL require exclusive ownership and a fresh validated state. Queue bookkeeping, timeouts, page disconnection, and old timestamps SHALL NOT prove prior execution inactivity. Reads SHALL NOT perform takeover. Terminal Runs SHALL accept no new execution or source writes; Session deletion SHALL wait for relevant execution ownership release.

Ownership SHALL be released only after the slice has no active dispatch and has committed stable progress. Persisted retry waiting SHALL not retain ownership; queue ownership alone SHALL not authorize execution.

#### Scenario: Two executors contend
- **WHEN** two processes attempt to advance the same Run
- **THEN** only one advances facts or effects and the other returns a bounded unavailable result without failing the Run

#### Scenario: Owner remains active
- **WHEN** a running tool is slow and a stop request has been accepted
- **THEN** the Run remains stopping/running until cooperative return or confirmed owner exit, without premature interruption or deletion
