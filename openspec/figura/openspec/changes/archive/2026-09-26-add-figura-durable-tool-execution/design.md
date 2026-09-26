## Context

See proposal.md and the delta specifications. The current SQLite schema is version 1. Its core execution-record table allows only input, model_response, and final_answer facts with a 256 KiB payload cap. The checkpoint tracks one core record sequence and only model/final actions. ToolRuntime already validates and invokes one synchronous tool call at a time; each ToolDefinition declares a replay effect, while ToolContext exposes run_id and call_id. The durable executor, tool facts, and recovery policy do not exist yet.

## Goals / Non-Goals

**Goals:**

- Preserve all existing v1 Run data and add durable tool execution without rebuilding the existing immutable core-record table.
- Persist model-associated tool-call intents, attempt starts, and outcomes in a validated per-Run stream.
- Make the checkpoint sufficient to resume the next tool or model action without reads invoking tools.
- Implement the agreed replay-effect policy with a stable identity for idempotent local writes.
- Keep tool execution facts private from existing public summaries and lifecycle events.

**Non-Goals:**

- Persist or replay ProviderContinuation; responses containing continuation remain unsupported by this change.
- Send Provider requests, build prompt history, or run the Agent ReAct loop.
- Add chart, attachment, measurement, or rendering tools.
- Retry a known failed result, parallelize a batch, or provide a generic remote reconciliation service.

## Decisions

### 1. Store tool facts in an additive, separately sequenced stream

Add an append-only run_tool_execution_facts table with run_id, tool_sequence, fact_kind, schema_version, payload_json, and created_at. tool_sequence is contiguous per Run and independent of the existing core record sequence. RunState returns both ordered streams. ToolCallFact references its parent model_response record and records its 0-based provider position; attempt and result facts reference the call fact and attempt_id.

This keeps tool intents/results immutable and ordered while avoiding a destructive rewrite of run_execution_records, whose kind CHECK and foreign-key relationships would otherwise require a high-risk SQLite table rebuild. The alternative, putting every fact in the existing table, offers one sequence but substantially complicates migration and couples new tool payload limits to the original table.

### 2. Advance both fact cursors and action in each transaction

Add last_committed_tool_sequence to ExecutionCheckpoint with a default of zero for migrated databases. Checkpoint actions are model, tool_execution, tool_attempt, and final. A tool_execution action points to the next call. begin_tool_attempt atomically appends the attempt-start fact, advances the tool cursor, and changes the action to tool_attempt with its attempt_id. A result commit atomically appends the result and moves to the next call or model action. A text-only stop response moves to final; completing a Run remains an atomic final-answer transition.

A model response with calls is associated with the exact ToolRegistry.version used by the request. The internal commit API requires that version when calls are present. It commits the core ModelResponseFact, all ordered ToolCallFacts, both sequence values, and the first tool action in a single SQLite transaction. A response with provider continuation is rejected without writes. Repeated model/tool rounds are representable in the store, but this change does not issue those model requests.

RunStatus remains running while a checkpoint is waiting for safe recovery or reconciliation. The blocked condition is represented by the tool_attempt action and the unresolved attempt fact; no new public RunStatus is added before Gateway/UI presentation is designed. The existing terminal statuses remain terminal.

### 3. Hold a per-Run execution lock across the external handler

A DurableToolExecutor acquires an exclusive per-Run process lock before starting or recovering a tool attempt. It holds the lock through the handler invocation and the result transaction. The SQLite expected-revision update remains the durable compare-and-swap guard for competing callers. Recovery may classify an attempt as orphaned only after it acquires the same lock, which proves the prior process no longer holds it. Do not reclaim an attempt based only on a time-based lease expiry: a delayed but live handler could otherwise overlap with its replay.

If the platform cannot acquire the execution lock, execution fails closed and leaves the checkpoint unchanged. Different Runs may execute independently. The lock implementation stays behind a small runtime adapter and introduces no new service or distributed-worker system.

### 4. Apply replay_effect only to attempts without a committed result

Persist the declared ReplayEffect and registry version in each ToolAttemptStartedFact.

- replay_safe: on explicit recovery after acquiring the Run lock and confirming the same registry version, start a new attempt for the same call_id. The result may differ from what the lost attempt would have returned; the newly observed result is the one recorded.
- idempotent_local_write: derive a stable key from canonical JSON containing run_id and call_id, hash it with SHA-256, and expose the resulting 64-character key as ToolContext.idempotency_key. The key is stable across attempts and does not contain attempt_id. A handler declaring this effect must use the key to deduplicate its local write and return the original result when the operation already exists.
- reconcile_required: never invoke the handler again automatically. Keep the checkpoint at tool_attempt until a trusted internal reconciliation caller commits the observed result for the same call and attempt.
- missing/unknown effect, unavailable registry version, or inability to prove the prior owner inactive: keep the attempt unresolved and fail closed.

A ToolExecutionResult already committed as succeeded or failed is not retried by this executor. Its error.retryable field does not override replay_effect. A handler that returns a failed ToolExecutionResult has completed the current attempt; a later model decision to call a tool again belongs to the future Agent loop.

### 5. Keep records bounded and preserve the existing event contract

Use no more than 64 calls per response, at most 64 KiB UTF-8 arguments per call, and at most 1 MiB aggregate argument bytes. Keep ToolExecutionResult's canonical result-object limit at 256 KiB; set the complete encoded tool fact bound to 512 KiB to leave room for its envelope. Each fact is encoded and checked before its SQLite write. A batch exceeding its aggregate bound is rejected before any response or call-intent facts are committed.

The existing run_stream_events table and public Run summary remain unchanged. Tool arguments, results, error details, and idempotency keys remain internal durable data and are excluded from public projections and ordinary logs. Lifecycle events continue to describe only Run lifecycle transitions.

### 6. Migrate v1 databases forward without rewriting existing facts

Set the SQLite schema version to 2. For an existing v1 database, acquire the writer lock and perform one transaction that creates run_tool_execution_facts, adds last_committed_tool_sequence with default 0, preserves existing action JSON decoding, and updates user_version only after schema and foreign-key checks succeed. Existing record rows, identifiers, sequences, payloads, events, idempotency mappings, and immutable triggers remain intact. A new database is created directly with the v2 schema.

Migration is forward-only. If any DDL, copy/validation, or foreign-key check fails before commit, roll back and leave the v1 database usable. The migration does not rewrite committed run facts or terminal states.

### 7. Fail closed on inconsistent history

RunState validation checks both sequences for continuity, validates call→response and attempt/result references, enforces tool positions and unique call IDs, and verifies that checkpoint cursors/actions match the committed facts. A model response with calls cannot be followed by another model response until every call has a committed result or a reconciled outcome. Reads validate and return state only; they never acquire execution authority or replay an attempt.

## Risks / Trade-offs

- [Replay classification is declared by each tool author] → Treat unknown values as blocked, snapshot the classification and registry version on the attempt, and require the idempotent-write contract to return the prior result.
- [A handler may finish its side effect immediately before the process dies] → The missing result remains an unknown attempt; only replay_safe or correctly idempotent work may be repeated, while reconcile_required stays blocked.
- [A process lock may be unavailable on a platform or data root] → Fail closed without invoking a handler; verify the supported lock adapter in implementation.
- [The new fact stream could diverge from core records] → Commit cross-stream response/call/checkpoint transitions in one SQLite transaction and validate references on every RunState read.
- [The v1 schema has circular foreign-key relationships] → Use additive DDL only; do not rebuild core tables. Verify foreign keys and preserve v1 rows before committing user_version=2.
- [Result payloads may be larger than the envelope bound] → Enforce the 256 KiB canonical result and 512 KiB complete fact limits before result commit; a failure to encode is not allowed to advance the checkpoint or fabricate a result.

## Migration Plan

1. On a fresh database, create the current core schema plus the v2 tool-fact table and checkpoint cursor.
2. On v1, acquire the SQLite writer transaction; create the tool-fact table and append-only triggers; add the zero-default tool cursor; preserve old action decoding; validate existing rows and foreign keys; set user_version=2 last.
3. Open a migrated Run and confirm its existing record/event/idempotency state is unchanged while its tool cursor is zero.
4. If migration fails before commit, roll back the transaction and continue to report a bounded storage/version error; do not delete or replace the database.
5. No v2-to-v1 downgrade is supported. A rollback uses the application's normal pre-migration SQLite backup/restore procedure; this change does not invent an alternate data-export path.


