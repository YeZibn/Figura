## Context

See `proposal.md` for motivation. Today Gateway Run is already `running/completed/failed/interrupted`, while Agent checkpoints copy messages, pending tool calls, measurement sessions and review snapshots. Memory records and Gateway checkpoints use separate SQLite connections even when they resolve to the same database file. Generated images are staged in Gateway storage, but candidate/review/publication statuses and a derived execution gate also travel through Agent, Gateway, SSE, frontend and OpenSpec. Old data does not need migration; new sessions created after cutover must still remain durable.

## Goals / Non-Goals

**Goals:**

- One committed execution source for continuation, one typed next-action cursor, and no second business lifecycle controlling the Run.
- Maintain safe source binding, automatic verification, bounded repair guidance, collection child attribution, failed-image preview and code-enforced publication/final-answer checks.
- Finish with old runtime state, callback, schema, protocol and UI branches removed; reset only configured Figura-managed legacy session/attachment/artifact data at cutover.

**Non-Goals:**

- Arbitrary instruction-level recovery, exactly-once provider billing, external side-effect tool integration, or a general workflow engine.
- Changing ChartSpec semantics, measurement quality policy, Gateway loopback/security limits, or the public Run/SSE identity contract.
- Migrating old run history/checkpoints or deleting external source images, diagnostics, evaluation bundles, `.env`, or unrelated files.

## Decisions

### 1. Immutable private execution entries plus one cursor

Store model response, tool result, verification result, promotion result and final answer as ordered private execution entries keyed by `run_id` and sequence. A committed entry contains the exact bounded data needed for later model context; provider-private continuation content, when required (for example DeepSeek reasoning), uses the existing exceptional private boundary and must never enter session transcript, SSE, trace or evaluation projection. Ordinary memory and public Gateway events become read models, never a second recovery authority. Keep completed-run context isolation: an interrupted parent is visible only to explicit resume.

The checkpoint has `version`, `run_id`, `entry_cursor`, `turn`, a tagged `next_action`, and only active opaque attachment/panel/measurement/staged/artifact refs and policy/provider versions that cannot be reconstructed from committed entries. Do not store messages, `pendingToolCalls`, `pendingReview`, serialized measurement sessions, review state or execution gate. `next_action` variants are `model`, `tool(message_entry_id, call_id)`, `verify(staged_ref)`, `promote(staged_ref, verification_ref)` and `final(answer_entry_id)`; `render` is a tool. A checkpoint always points to a fully committed prefix. The last phase is derived from that prefix rather than persisted beside the next action.

Use a shared SQLite write transaction to insert a step entry, update the checkpoint cursor and persist any associated public event/outbox record. Do not publish a step to SSE before commit. A new child resume Run references the immutable parent prefix and writes its own entries; original terminal status and event sequence remain unchanged. Work identities derive from the root run, committed model entry, tool call and output ordinal, not from arguments alone, so an intentional repeat call remains a new attempt while a resumed call retains its identity.

Alternative rejected: copying the whole runtime state into each checkpoint; it produces multiple mutable authorities and size/security pressure. Alternative rejected: using sanitized session memory records alone; they omit private provider context needed for an exact tool continuation.

### 2. Per-action replay contract, without a universal Operation Journal

For each `next_action`, query committed entries first. A committed matching result is reused. An uncommitted read-only/compute tool can rerun. Local writes (render staging and promotion included) require a stable work key and idempotent reconciliation against their own stored result. On explicit resume, an uncommitted model or VLM request may be reissued; its previous remote result may have incurred token cost, and only the newly committed response becomes authoritative. Deterministic provider rejection remains an ordinary failed outcome. A future tool with an unqueryable external side effect requires a narrow reconcile guard and blocks replay if its outcome cannot be established. No current tool needs the universal model/tool/render/publication journal, so remove it and its factory callbacks.

Do not infer replay safety from a tool name. Declare the effect at the tool boundary and cover actual persistence behavior. Retain one Run budget across resumed parent/child execution for model steps and generated-chart attempts; derive attempt counts from committed entries and stable generation target identity, not a `repair_phase` state.

Alternative rejected: blanket block when any historical operation is `in_flight`; unrelated or locally reconcilable work can otherwise prevent safe continuation. Alternative rejected: automatic replay of unknown external effects.

### 3. Staged chart, immutable verification, idempotent promotion

Rendering writes a bounded image blob and immutable manifest under an opaque staged reference. The manifest binds work key, image digest, exact ChartSpec digest, authorized source attachment/panel/revision and generation context, figure/collection IDs, and verifier policy version. Write blob to a restricted temporary path, flush and atomically rename, then commit its manifest; a crash before manifest commit leaves an orphan eligible for scoped cleanup. The public staged reference is not the content digest alone: identical pixels may represent different source/spec claims.

Deterministic checks always run; source-linked or explicitly required charts also receive one tool-free VLM semantic decision for the attempt. The verifier performs source-binding preflight, uses the authorized scope, and saves an immutable bounded `pass`, `pass_with_warning`, `fail` or `unavailable` result with issues, repair hint/target, input digests and policy version. Only a matching nonblocking result under the declared policy permits promotion. Promotion rechecks those bindings in a transaction and inserts or returns the same published artifact for the attempt; the image bytes need not be moved. Failed/pending staged images remain available via a session/run-scoped preview route but are never downloadable as final artifacts.

Each collection child has its own staged/verification result and retained collection/figure correlation; a failed child cannot be presented as a passing sibling. Agent receives bounded result facts and selects any authorized next tool; repair hints do not authorize a tool, change source scope, or drive a repair state machine. A final-answer guard checks unresolved required verification and all claimed/generated artifact refs before terminal completion. An exhausted attempt limit produces an explicit unsuccessful terminal outcome with diagnostics.

Alternative rejected: a bare `ok` Boolean or content-hash-only artifact identity; neither represents permitted warnings nor proves which source/spec/policy was checked. Alternative rejected: storing Candidate, Review and Publication lifecycle snapshots for recovery.

### 4. Thin external projection and clean data cutover

Keep `runId:sequence`, run idempotency, interruption, retry/resume child lineage and bounded terminal error context. Derive `resumable` and a safe unavailable reason from terminal Run status, current checkpoint validity, refs, policy and replay contract; do not persist an independent RecoveryStatus state machine. Project only tool, verification, artifact and terminal facts into the user timeline. Use a stable correlation key and child ordinal for collection grouping. Frontend Gateway and mock adapters consume the same new contract; remove old candidate/review/publication status fields, gate banners and retired-event adapters rather than extending them.

At cutover, stop the Gateway and resolve `CHARTAGENT_DATA_DIR`, explicit `--data-dir`/database and attachment overrides with the same storage resolver the app uses. Inventory the exact canonical database, managed attachment root and run-artifact root, confirm they belong to this Figura instance and are writable, then delete only those legacy targets and initialize the new schema. Do not recursively delete `.chartagent` as a whole. This reset deliberately makes old sessions/history/artifacts unavailable. The new empty database remains durable for subsequent work. Avoid shipping a permanent old-schema reader or migrator.

Alternative rejected: preserving old history with dual format projection; this retains the very compatibility and state surface the change is meant to remove.

## Risks / Trade-offs

- [Private model context could leak into public records] → Separate private execution payload from sanitized transcript/events, bound size and permissions, and test that reasoning, paths, credentials and bytes never project outward.
- [Result commit and cursor advance could diverge] → One SQLite transaction for each durable step and its event projection; resume validates the referenced committed prefix.
- [File and SQLite cannot share a transaction] → Atomic blob rename before manifest commit, digest verification on read, orphan cleanup, and idempotent re-stage by work key.
- [Reissued model/VLM request may cost more or vary] → Reissue only on explicit resume for an uncommitted result; expose this contract, reuse every committed response, and never treat a rejected or unverified image as published.
- [Deleting old state changes many producers/consumers] → Cut over Gateway, CLI, prompt, frontend mock/real adapters and evaluation projection together within this change; require zero production references to retired symbols and no permanent adapter.
- [Legacy data reset is irreversible] → Inventory exact configured paths after stopping services; preserve external source images and out-of-scope diagnostics/evaluations; validate new empty-store startup before considering the change complete.

## Migration Plan

1. Implement and validate the private entry/cursor transaction and explicit resume against fresh test stores; remove old checkpoint and generic operation writes as their callers move.
2. Implement staged chart verification and promotion through Agent/Gateway, including source and collection behavior; replace review/gate callbacks and final-answer checks.
3. Switch SSE, Gateway/mock client, timeline, preview, prompt and evaluation projections; delete old state classes, columns, endpoints/events and compatibility branches, then update the corresponding main specs through the OpenSpec workflow.
4. Run fault-injection cases at every safe boundary, the repository's Python/frontend checks, and a real Gateway interaction. Stop processes, resolve and inspect the exact configured legacy paths, remove the old managed session database/attachments/run artifacts, and verify fresh-start behavior and final `git diff --check`.

Rollback before data reset is a code revert against the still-existing old store. After reset, code can be reverted but deleted legacy data cannot be restored by this change; therefore the reset is the last cutover action after validation.
