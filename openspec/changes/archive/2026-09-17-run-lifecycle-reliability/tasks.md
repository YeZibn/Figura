## 1. Contract and storage foundation

- [x] 1.1 Define the run lifecycle status, terminal reason, idempotency conflict, and `history_gap` machine-code contracts in the shared Python protocol types.
- [x] 1.2 Add an additive SQLite migration for idempotency records, terminal reason/message/timestamp fields, cancel-request state, and retry parent references.
- [x] 1.3 Implement bounded normalization and fingerprinting for session, text, attachment IDs, and effective provider without including secrets or local paths.
- [x] 1.4 Add persistence queries for idempotency lookup, atomic key binding, run summary retrieval, terminal transition, and retry lineage.

## 2. Run lifecycle and terminal gate

- [x] 2.1 Refactor the managed-run state transition path so completed, failed, and interrupted outcomes share one serialized terminal gate.
- [x] 2.2 Guard event publication and terminal event creation against already-terminal runs while preserving the last valid pre-terminal trace.
- [x] 2.3 Add a cooperative interruption signal to the in-process run context and make repeated interruption requests return the existing state.
- [x] 2.4 Propagate interruption results through the worker wrapper so provider/tool/render/review callbacks cannot overwrite a terminal run.
- [x] 2.5 Update Gateway startup/restart recovery to terminalize previously active runs with `gateway_restarted` and make the terminal outcome replayable from summary or event history.

## 3. Gateway request and HTTP API

- [x] 3.1 Extend asynchronous run creation to read `Idempotency-Key`, bind an equivalent request to the original run, and return `idempotency_conflict` for a mismatched fingerprint.
- [x] 3.2 Close the accept-before-submit failure window by terminalizing a persisted run when worker submission fails, while keeping its idempotency binding.
- [x] 3.3 Add an authorized run-interruption operation with session ownership checks, bounded reason codes, and idempotent terminal behavior.
- [x] 3.4 Add explicit retry input/output fields so a retry receives a new run and idempotency identity plus a bounded `retry_of` reference.
- [x] 3.5 Preserve compatibility for requests without an idempotency key and document that only keyed first-party submissions receive duplicate-submission protection.

## 4. Event replay and SSE recovery

- [x] 4.1 Make historical and live run events share one monotonic per-run cursor contract and return `history_gap` when the requested cursor is no longer retained.
- [x] 4.2 Update the SSE endpoint to honor `Last-Event-ID`/after-sequence consistently, replay retained events before live tailing, and close cleanly for terminal runs.
- [x] 4.3 Ensure run history and summaries expose the authoritative terminal state even when a restart could not append a terminal event.
- [x] 4.4 Add server-side tests for duplicate replay, cursor boundaries, history gaps, terminal close, and callbacks attempting to publish after terminalization.

## 5. Agent cooperative interruption

- [x] 5.1 Add interruption checks before each model request and native tool dispatch in the Agent loop.
- [x] 5.2 Add interruption checks before publishing tool observations, generated visuals, review context, and final answer data.
- [x] 5.3 Return a bounded interrupted result without starting the next work unit, while preserving valid trace data produced before interruption.
- [x] 5.4 Add Agent-loop tests for interruption between tool calls and late provider/tool results.

## 6. Frontend identity, reconnect, and state model

- [x] 6.1 Extend client contracts and the Gateway adapter with `Idempotency-Key`, `retry_of`, interruption, terminal-reason, and `history_gap` fields.
- [x] 6.2 Generate one idempotency key per new submit intent, persist it with the active run context, and reuse it only for acknowledgement/reconnect recovery.
- [x] 6.3 Replace the current fixed reconnect flow with last-applied-sequence recovery, replay deduplication by run ID and sequence, bounded exponential backoff with jitter, and terminal-aware stop conditions.
- [x] 6.4 Add explicit `reconnecting`, `history-gap`, `interrupted`, and `cancel_requested` UI state mappings with Simplified Chinese labels and safe fallback text.
- [x] 6.5 Add a user interruption action and keep it separate from transport disconnect handling.
- [x] 6.6 Add an explicit retry action that creates a new run/key, displays the retry parent relationship, and preserves the original run timeline.

## 7. Verification and documentation

- [x] 7.1 Add Gateway regression coverage for concurrent equivalent submissions, conflicting key reuse, lost acknowledgement, worker-submit failure, interruption races, restart recovery, and retry lineage.
- [x] 7.2 Add frontend/mock adapter coverage for repeated submission identity, SSE replay duplicates, history gaps, bounded reconnect exhaustion, interruption, and retry separation.
- [x] 7.3 Run Python tests with `conda run -n agent python -m pytest -q` and verify `rapidocr` from the `agent` environment if dependency diagnostics are needed.
- [x] 7.4 Run `npm run build`, `npm run smoke`, and `git diff --check` after implementation.
- [x] 7.5 Update Gateway/client lifecycle documentation and API examples to explain keyed submission, reconnect versus retry, interruption reasons, and the non-resumable Gateway restart behavior.
