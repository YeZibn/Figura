## MODIFIED Requirements

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

### Requirement: Execution ownership gates takeover and mutation
Figura SHALL establish exclusive cross-process ownership for each execution task or action slice, including every active handler, and SHALL separately protect action execution and recovery. Takeover SHALL require exclusive ownership and a fresh validated state. Queue bookkeeping, timeouts, page disconnection, and old timestamps SHALL NOT prove prior execution inactivity. Reads SHALL NOT perform takeover. Terminal Runs SHALL accept no new execution or source writes; Session deletion SHALL wait for relevant execution ownership release.

Ownership SHALL be released only after the slice has no active dispatch and has committed stable progress. Persisted retry waiting SHALL not retain ownership; queue ownership alone SHALL not authorize execution.

#### Scenario: Two executors contend
- **WHEN** two processes attempt to advance the same Run
- **THEN** only one advances facts or effects and the other returns a bounded unavailable result without failing the Run

#### Scenario: Owner remains active
- **WHEN** a running tool is slow and a stop request has been accepted
- **THEN** the Run remains stopping/running until cooperative return or confirmed owner exit, without premature interruption or deletion

## RENAMED Requirements

- FROM: `### Requirement: Recovery never resends a started provider attempt`
- TO: `### Requirement: Recovery closes orphaned provider attempts before eligible replacement`
