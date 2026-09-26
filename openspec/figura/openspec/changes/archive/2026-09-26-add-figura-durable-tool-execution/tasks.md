## 1. Durable tool-execution domain and codecs

- [x] 1.1 Add typed tool-call, attempt-start, and tool-result payloads plus the separately sequenced tool-fact envelope; retain model responses in the existing core record stream.
- [x] 1.2 Extend checkpoint actions with `tool_execution` and `tool_attempt`, add `last_committed_tool_sequence`, and define the action references needed to resume the exact call and attempt.
- [x] 1.3 Add strict encoding and decoding for tool facts, references, replay-effect values, and the 64-call, 64 KiB-per-argument, 1 MiB aggregate-argument, 256 KiB canonical-result, and 512 KiB complete-fact bounds.
- [x] 1.4 Add RunState validation for contiguous independent sequences, response/call/attempt/result references, ordered positions, unique call IDs, resolved batches, and checkpoint/action consistency.

## 2. SQLite persistence and atomic transitions

- [x] 2.1 Implement the additive schema v1-to-v2 migration: create the append-only `run_tool_execution_facts` table and triggers, add the zero-default tool-fact checkpoint cursor, and preserve existing core records and constraints.
- [x] 2.2 Extend fresh-database creation, RunState reads, and storage codecs to load both fact streams and validate migrated as well as new Runs.
- [x] 2.3 Persist a model response and its ordered tool-call intents with the registry version and first tool action in one transaction; reject continuation-bearing or invalid batches without partial writes.
- [x] 2.4 Implement compare-and-swap transactions for attempt-start and result facts, advancing the tool cursor/action atomically and rejecting stale, duplicate, cross-Run, or out-of-order transitions.
- [x] 2.5 Add migration and store tests proving v1 data preservation, foreign-key integrity, rollback on migration failure, atomicity, and independent sequence continuity.

## 3. Durable executor and recovery

- [x] 3.1 Add a per-Run execution lock held from attempt claim through handler completion and result commit; fail closed when exclusive ownership cannot be proven.
- [x] 3.2 Implement serial provider-order dispatch through ToolRuntime, persisting attempt-start before invocation and committing each bounded success or failure before advancing.
- [x] 3.3 Snapshot `replay_effect` and registry version; after confirming the old owner is inactive, replay `replay_safe`, replay `idempotent_local_write` with the stable SHA-256 key derived from canonical `[run_id, call_id]`, and keep `reconcile_required` unresolved until a trusted result is committed.
- [x] 3.4 Expose the computed idempotency key through `ToolContext`; require idempotent local-write handlers to return the original result for an already-applied key.
- [x] 3.5 Ensure RunState reads never dispatch work and keep tool arguments, results, errors, and idempotency keys out of public summaries, lifecycle events, and ordinary logs; add recovery, concurrency, and privacy tests.

## 4. Compatibility and acceptance

- [x] 4.1 Preserve text-only Run behavior, existing v1 identifiers and event contracts, continuation rejection, and the rule that completion cannot bypass pending or unresolved tool work.
- [x] 4.2 Add end-to-end store/executor coverage for ordered batches, known failures, duplicate result commits, replay classifications, registry mismatch, owner-lock contention, payload limits, and restart reads.
- [x] 4.3 Run the focused Figura runtime/tool tests and the repository validation required for the implementation; record exact commands and outcomes before reconciling the implementation record.
