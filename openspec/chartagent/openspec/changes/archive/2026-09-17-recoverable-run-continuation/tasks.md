## 1. Recovery Contract and Persistence

- [x] 1.1 Define bounded recovery statuses, checkpoint phases, operation states, continuation kinds, stable recovery error codes, and normalized parent/child lineage fields in the shared Python and TypeScript protocol types.
- [x] 1.2 Add an additive SQLite migration for run lineage and recovery metadata plus bounded checkpoint and operation-ledger tables with indexes and expiry fields.
- [x] 1.3 Implement checkpoint serialization, sanitization, size limits, schema-version validation, digest generation, and authorized attachment/artifact reference handling.
- [x] 1.4 Implement journal operations for creating a checkpoint, beginning and completing a work unit, recording an uncertain operation, reading recovery status, and atomically binding a resume idempotency key.
- [x] 1.5 Add retention cleanup and compatibility behavior for legacy runs that have no checkpoint or use an unsupported checkpoint version.

## 2. Run Lifecycle and Gateway Recovery

- [x] 2.1 Extend managed and historical run projections with normalized continuation lineage, recovery metadata, checkpoint phase, and bounded blocked reasons while keeping terminal runs immutable.
- [x] 2.2 Add serialized checkpoint and operation-boundary hooks to the managed run path so durable checkpoint state is committed before its corresponding progress event is published.
- [x] 2.3 Update Gateway restart recovery to preserve the last committed checkpoint, classify recovery as available or blocked, and keep existing `gateway_restarted` terminal behavior.
- [x] 2.4 Add an authorized resume operation that validates session ownership, parent terminal state, checkpoint version, expiry, recovery status, and a new idempotency key before creating a child run.
- [x] 2.5 Bind duplicate resume requests to the original child run and terminalize a child safely when worker submission fails, without changing the parent run.
- [x] 2.6 Expose recovery metadata and stable recovery-blocked/unavailable errors through run summaries, history responses, and the resume route without leaking internal state or local paths.

## 3. Agent Context and Continuation Execution

- [x] 3.1 Add explicit memory APIs for reading a parent run's validated recovery context into a new child run while keeping interrupted and uncertain runs out of ordinary new-turn context.
- [x] 3.2 Extend Agent execution input to hydrate bounded messages, current turn, next action, safe tool results, and continuation references from a validated checkpoint.
- [x] 3.3 Record model, tool, rendering, review, and publication work units with stable operation identities and `not_started`, `in_flight`, `completed`, or uncertain outcomes.
- [x] 3.4 Reuse durably completed operation results during continuation and stop with a bounded recovery-blocked outcome for uncertain operations without a replay-safe contract.
- [x] 3.5 Persist and rehydrate layout contexts, visual evidence references, generated chart candidates, review state, and publication state; mark recovery unavailable when required state cannot be authorized or reconstructed.
- [x] 3.6 Preserve cooperative interruption and terminal rules so a resumed child cannot publish a final answer or mutate the parent after interruption or terminalization.

## 4. Chart Artifact and Review Consistency

- [x] 4.1 Make candidate, VLM review, and publication records addressable by stable run/call/candidate identities and safe to reuse during a continuation.
- [x] 4.2 Make generated chart and visual observation references reloadable through the existing authorized resource paths, with bounded unavailable states for expired artifacts.
- [x] 4.3 Guard chart publication and review completion against duplicate continuation attempts and preserve the original candidate/publication outcome.
- [x] 4.4 Add trace projection fields and events for checkpoint creation, operation completion, recovery blocking, and resume lineage without exposing sensitive checkpoint payloads.

## 5. Desktop Client and Mock Boundary

- [x] 5.1 Extend client contracts and Gateway adapters with recovery metadata, normalized continuation lineage, resume requests, idempotency handling, and recovery error mapping.
- [x] 5.2 Add explicit `继续执行`, `重新尝试`, and reconnect state handling, showing the bounded checkpoint phase and Chinese fallback text for blocked or unavailable recovery.
- [x] 5.3 Render resumed child runs with their parent relationship while retaining independent event cursors, terminal summaries, generated chart previews, and original timelines.
- [x] 5.4 Ensure reload discovers recoverable runs without automatically starting them, and ensure transport reconnect never invokes resume or retry.
- [x] 5.5 Extend the mock client and frontend smoke coverage for available recovery, blocked recovery, duplicate resume, parent immutability, reconnect, and retry separation.

## 6. Regression and Fault-Injection Coverage

- [x] 6.1 Add protocol and persistence tests for checkpoint bounds, schema versions, expiry, operation state transitions, idempotent resume binding, and legacy runs.
- [x] 6.2 Add Agent tests for continuation after completed model/tool work, layout and chart evidence hydration, review/publication hydration, interruption, and uncertain-operation blocking.
- [x] 6.3 Add Gateway tests for restart recovery, cross-session authorization, duplicate/concurrent resume, missing or expired checkpoints, worker-submit failure, parent immutability, and terminal replay.
- [x] 6.4 Add failure-injection tests around model response persistence, tool result persistence, chart rendering, VLM review, and publication commit boundaries.
- [x] 6.5 Run the Python suite with `conda run -n agent python -m pytest -q` and verify `rapidocr` from the `agent` environment if dependency diagnostics are needed.
- [x] 6.6 Run `npm run build`, `npm run smoke`, and `git diff --check`; document the restart, reconnect, resume, retry, and recovery-blocked acceptance matrix.
