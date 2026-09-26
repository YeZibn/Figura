# durable-tool-execution Specification

## Purpose

Provides durable, ordered tool execution for Figura Runs so a tool effect and its result can be recovered after process interruption without blindly duplicating side effects.

## Requirements

### Requirement: Tool-call intents are committed with their model response
Figura SHALL persist tool-execution facts in a per-Run monotonically increasing sequence separate from the core record sequence. It SHALL persist a normalized model response and all associated tool-call intents as one atomic Run progress transition. A response containing tool calls SHALL use the tool_calls finish reason and SHALL contain no provider-private continuation in this change. Tool-call intents SHALL retain the response reference, opaque call ID, tool name, raw bounded JSON arguments, provider order, and the tool registry version used to produce the call. One response SHALL contain no more than 64 calls, each argument SHALL be no larger than 64 KiB UTF-8, and aggregate argument bytes SHALL not exceed 1 MiB. Call IDs SHALL be unique within the Run and positions SHALL be contiguous starting at zero.

#### Scenario: Commit a bounded tool-call batch
- **WHEN** a current model action receives a valid response with one or more bounded tool calls, no provider-private continuation, and the expected checkpoint revision
- **THEN** Figura persists the response and all ordered call intents together and advances the checkpoint to the first call

#### Scenario: Reject an invalid or oversized batch
- **WHEN** a response has duplicate call IDs, invalid positions, more than 64 calls, an argument over 64 KiB, or aggregate arguments over 1 MiB
- **THEN** Figura rejects the response without adding any response, tool-call, checkpoint, or event facts

#### Scenario: Reject provider-private continuation
- **WHEN** a response contains provider-private continuation
- **THEN** Figura rejects the commit without changing the Run record prefix or checkpoint

### Requirement: Tool attempts are recorded before handler invocation
Figura SHALL append a durable attempt-start fact and advance the checkpoint before invoking a tool handler. A start fact SHALL reference the same Run's call intent and snapshot its attempt identity, attempt number, replay-effect classification, and registry version. Tool calls in one response SHALL execute one at a time in provider order. Only one executor SHALL be able to claim the current call; a stale checkpoint or a call already in progress SHALL NOT invoke another handler.

#### Scenario: Start the next call in a batch
- **WHEN** the checkpoint points to a pending tool call and the caller supplies the current revision and matching registry version
- **THEN** Figura atomically records the attempt start and current attempt reference before the handler is invoked

#### Scenario: Competing executor claims a call
- **WHEN** two executors attempt to start the same pending call from the same checkpoint revision
- **THEN** at most one obtains the attempt and the other does not invoke the handler

#### Scenario: Tool call belongs to a different Run or registry version
- **WHEN** an attempt references a call from another Run or a registry version that does not match the committed intent
- **THEN** Figura rejects the transition without invoking a handler or advancing the checkpoint

### Requirement: Tool outcomes and checkpoint progress commit atomically
Figura SHALL persist each returned success or failure as a bounded tool-execution fact associated with the exact call and attempt. A successful result SHALL contain a JSON object whose canonical encoding is no larger than 256 KiB; the complete encoded tool fact SHALL be no larger than 512 KiB. A failed result SHALL contain only a bounded structured error. Committing an outcome and advancing the tool-fact sequence and checkpoint to the next tool call or model action SHALL be atomic. A previously committed result SHALL be returned from durable state and SHALL NOT invoke the handler again.

#### Scenario: Commit a successful tool result
- **WHEN** the current attempt returns a successful bounded object result and the expected revision is current
- **THEN** Figura appends the result fact and advances the checkpoint to the next call or, after the batch, to a model action in the same transaction

#### Scenario: Commit a failed tool result
- **WHEN** the current attempt returns a bounded structured failure
- **THEN** Figura persists the failure against the same call ID and attempt ID and advances progress atomically without retrying the handler

#### Scenario: Repeat a result commit
- **WHEN** a caller tries to commit another result for an attempt that already has a committed result
- **THEN** Figura rejects the duplicate transition and retains the original result and checkpoint

### Requirement: Unknown tool outcomes follow the declared replay effect
After recovery finds an attempt-start fact with no corresponding result, Figura SHALL treat the outcome as unknown and SHALL NOT assume the handler did not run. Recovery SHALL begin only after the prior execution owner is confirmed inactive and the committed registry version remains available. For replay_safe calls, Figura SHALL create a new attempt for the same logical call ID when recovery is requested. For idempotent_local_write calls, Figura SHALL create a new attempt only with the same stable idempotency key derived from canonical JSON `[run_id, call_id]`, and the handler contract SHALL return the prior operation result when that key was already applied. Figura SHALL expose this key only as `ToolContext.idempotency_key`; ToolRuntime SHALL refuse to invoke an idempotent local-write handler when the key is absent. For reconcile_required calls, Figura SHALL NOT invoke the handler again until a trusted reconciliation result is committed. Missing/unknown classifications and registry mismatches SHALL remain unresolved and SHALL fail closed. A known failed result SHALL not be retried by this capability based solely on its retryable field.

#### Scenario: Replay a replay-safe call after owner exit
- **WHEN** recovery confirms the prior executor is inactive, the registry version matches, and an unresolved attempt is classified replay_safe
- **THEN** Figura starts a new attempt for the same logical call ID, records the new attempt number, and invokes the handler again only after the old execution owner is confirmed inactive

#### Scenario: Replay an idempotent local write
- **WHEN** recovery confirms the prior executor is inactive and an unresolved idempotent_local_write call is replayed
- **THEN** Figura uses the same stable Run/call idempotency key so a previously applied operation returns its prior result instead of creating a duplicate effect

#### Scenario: Require an idempotency key before local-write dispatch
- **WHEN** an idempotent_local_write invocation reaches ToolRuntime without `ToolContext.idempotency_key`
- **THEN** the runtime returns a bounded failure without invoking the handler

#### Scenario: Hold a call that requires reconciliation
- **WHEN** an unresolved attempt is classified reconcile_required
- **THEN** Figura does not invoke the handler again and keeps the call pending until a trusted reconciliation outcome is committed

#### Scenario: Fail closed on an unverifiable attempt
- **WHEN** the replay classification is missing or unknown, the old executor may still be active, or the recorded registry version is unavailable
- **THEN** Figura does not dispatch the call and exposes a bounded unresolved state to the recovery owner

### Requirement: Recovery reads do not execute tools and execution facts remain private
Figura SHALL reconstruct the core record sequence, tool-execution fact sequence, and checkpoint state without invoking a provider or tool. Tool arguments, results, continuation payloads, credentials, raw endpoints, and local paths SHALL NOT appear in public Run summaries, lifecycle events, or ordinary diagnostic logs. Each complete encoded tool-execution fact SHALL fit within 512 KiB; oversized batches SHALL be rejected before any batch facts are committed.

#### Scenario: Read a Run after process restart
- **WHEN** an internal caller reads a Run containing a pending, completed, or unresolved tool attempt
- **THEN** Figura returns the consistent committed fact prefix and checkpoint without calling ToolRuntime or automatically replaying work

#### Scenario: Keep execution payloads out of public projections
- **WHEN** a Run summary or lifecycle event is serialized
- **THEN** it contains only allowlisted lifecycle/status fields and omits tool arguments, result payloads, and private continuation
