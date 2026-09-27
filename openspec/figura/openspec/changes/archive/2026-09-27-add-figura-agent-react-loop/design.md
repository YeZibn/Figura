## Context

See `proposal.md` for motivation and scope. The current `src/figura` implementation already has the pieces this change must coordinate:

- `RunCoordinator` validates Run transitions and delegates atomic writes to `FiguraRunStore`.
- `FiguraRunStore` persists immutable Run records, ordered tool facts, checkpoints, lifecycle events, and provider continuations. The database schema is currently version 3.
- `ProviderClient.complete()` makes one synchronous request and the provider layer does not retry or switch providers.
- `DurableToolExecutor` serializes persisted tool calls and records an attempt before invoking a handler. Its explicit recovery methods are separate from a normal `execute_pending()` call.
- `project_provider_tools()` projects registry metadata without exposing handlers.

There is no current `src/figura/agent/` execution owner. `ActionKind` currently has `MODEL`, `TOOL_EXECUTION`, `TOOL_ATTEMPT`, and `FINAL`. Model responses can be committed directly at a model checkpoint, so a process restart cannot prove whether a provider request had already been dispatched.

The current Agent v1 boundary is one text input, one explicitly selected provider/model for the Run, synchronous non-streaming calls, and the existing bounded provider/tool contracts. A model response with tool calls and its continuation are already committed with their durable call intents; this change adds the missing model-request claim and scheduler around those contracts.

## Goals / Non-Goals

**Goals:**

- Add a single checkpoint-driven owner for request assembly, Provider invocation, sequential tool execution, and finalization.
- Rebuild every request from committed Run facts; do not maintain an independent mutable chat-history list.
- Persist a provider attempt before dispatch and make response/failure/recovery transitions atomic and fail closed.
- Specify each added durable field, its owner, lifecycle, and migration behavior.
- Bound one Run to 8 durable provider attempts and 32 distinct tool calls whose execution is started.

**Non-Goals:**

- Adding production chart-analysis tools, attachments, streaming, Gateway or frontend entry points, cross-Run memory, new provider adapters, or fallback/retry policies.
- Automatically recovering, replaying, or reconciling an unresolved tool attempt in the ReAct scheduler.
- Persisting prompts, rendered provider requests, credentials, raw provider responses, or a second copy of conversation history.
- Introducing a `waiting` Run status or a second durable budget counter.

## Decisions

### 1. Keep orchestration, request projection, and persistence ownership separate

Add `src/figura/agent/request.py` as a pure projection from `RunState`, the selected immutable `ToolRegistry`, and the fixed v1 instruction asset to a `ProviderRequest`. It owns role mapping, tool-result serialization, complete-round trimming, and request-size checks. It performs no I/O and writes no state.

Add `src/figura/agent/executor.py` as the scheduler. It reads the checkpoint, invokes only that action, and loops after each committed transition. It does not open SQLite, own a second conversation list, invoke tool handlers directly, or implement replay policy.

Extend `RunCoordinator`/`FiguraRunStore` for the provider-attempt transactions. Keep `DurableToolExecutor` as the only tool invocation path; add a bounded `max_calls` argument to its normal pending execution so the Agent can spend only the remaining per-Run tool budget. Existing callers that omit the argument retain current behavior.

The intended dependencies are:

```text
AgentExecutor ──reads/advances──> RunCoordinator ──atomic transitions──> FiguraRunStore
      │                                  │
      ├──pure request projection──> AgentRequestBuilder
      ├──one selected request─────> ProviderClient
      └──bounded tool batch───────> DurableToolExecutor ──> ToolRuntime/ToolRegistry
```

Use the existing per-Run OS lock identity for both provider dispatch and tool dispatch. Hold it while claiming, sending, and committing one provider attempt. Do not hold it while calling `DurableToolExecutor`, which acquires the same per-Run lock itself. Checkpoint compare-and-swap remains the storage-level guard if a competing caller observed stale state.

### 2. Add one provider-attempt row and reuse existing Run/checkpoint identities

Add `ProviderAttempt` to `src/figura/runtime/models.py` and expose an ordered private `provider_attempts` tuple on `RunState`. Persist rows in `run_provider_attempts`; do not add fields to the public Run projection, stream events, provider response, tool facts, or `NextAction`.

| Field | Owner and meaning | Constraints and lifecycle |
| --- | --- | --- |
| `attempt_id` | RunCoordinator-generated opaque identity for this one model action | Unique; UTF-8 length 1–128 bytes. Reuse the existing `NextAction.attempt_id` field to identify the active attempt. |
| `run_id` | Owning Run | Required foreign key to `runs`; provider and model are read from this immutable Run row, so they are not duplicated. |
| `attempt_sequence` | Per-Run ordering and request-budget source | Positive contiguous integer beginning at 1; no more than 8. Inserted only when a current model action is claimed. |
| `base_record_sequence` | Last committed core record included when the attempt is claimed | Positive and equal to the checkpoint's committed record cursor at claim time. Together with `base_tool_sequence`, identifies the durable history prefix; it does not contain history text. |
| `base_tool_sequence` | Last committed tool fact included when the attempt is claimed | Nonnegative and equal to the checkpoint's tool cursor at claim time. |
| `status` | Durable provider-attempt lifecycle | Exactly `started`, `response_committed`, `known_failure`, or `outcome_unknown`. Only `started` may transition, once, to one of the other states. |
| `response_record_id` | Link from a successful attempt to its committed model response | Null unless status is `response_committed`; then required and a same-Run model-response foreign key. One attempt and one response map to each other. |
| `failure_code` | Safe bounded provider failure category from the existing `ProviderFailureCode` set | Null for `started` and `response_committed`; required for `known_failure`; optional for `outcome_unknown` because a process crash may provide no code. Never store raw exception text. |
| `started_at` | RunCoordinator timestamp when the claim commits | Required immutable timestamp. It records claim time, not proof that bytes reached the provider. |
| `finished_at` | RunCoordinator timestamp when a response or failure outcome commits | Null only while `started`; required for all terminal attempt statuses. |

The table additionally enforces unique attempt ID, unique per-Run sequence, unique per-Run base cursor pair, valid status/code combinations, and a composite same-Run response foreign key. It stores no prompt, messages, tool schema, continuation, endpoint, credential, raw response body, or provider/model copy. No per-row schema version is added: SQLite's `user_version` controls this table shape.

Add `ActionKind.PROVIDER_ATTEMPT`. Its encoded checkpoint action is `{ "action_kind": "provider_attempt", "attempt_id": "..." }`; it uses the existing `NextAction.attempt_id`, not a new action field. The claim inserts the attempt and advances checkpoint revision/action in one transaction. On success, update the attempt to `response_committed` in the same transaction that writes the model response, optional continuation, call intents, and next action. On failure, update the attempt and terminal Run/event in one transaction. A terminal Run retains the last committed checkpoint as current failure context, consistent with existing terminal transitions.

Add `TerminalCode.PROVIDER_OUTCOME_UNKNOWN` with one fixed safe message. Do not add a new `RunStatus`: unknown provider outcome is a failed Run that users can distinguish from other failures by terminal code. No provider-attempt event is emitted; the existing bounded `run_failed` event carries only the terminal code.

### 3. Use one state machine; never infer work from missing facts

| Current durable state | Agent action | Durable next state |
| --- | --- | --- |
| `running / MODEL` | Build and validate request, check budgets, acquire the Run lock, claim provider attempt, call the explicitly selected provider once, commit the normalized response | `TOOL_EXECUTION` for a tool-call batch; `FINAL` for a non-tool response |
| `running / TOOL_EXECUTION` | Ask `DurableToolExecutor` to execute at most the remaining distinct-call budget | Next tool action, `MODEL` after the full batch, or unchanged pending action when its slice ends |
| `running / TOOL_ATTEMPT` | Return the unresolved state; do not invoke recovery or send a model request | Unchanged until an explicit durable-tool recovery operation resolves it |
| `running / PROVIDER_ATTEMPT` | Only reachable after restart/owner loss; under the Run lock atomically resolve the started attempt as outcome unknown and fail the Run | `failed / provider_outcome_unknown` |
| `running / FINAL` | Validate that the referenced response is `stop` with non-whitespace content; complete, otherwise fail with `invalid_response` | `completed` or `failed` |
| terminal Run | Return the reconstructed state | No change and no external call |

Before any Provider call, the request builder must finish projection, trim if necessary, and pass Provider request validation. The factory may construct the selected local client before the claim because client setup does not submit a completion request. The claim must commit before calling `ProviderClient.complete()`.

If ProviderClient returns a validly normalized response, commit it first with its attempt. A `tool_calls` response advances to the first tool intent; a response with no calls advances to `FINAL`. The Agent then accepts only `tool_calls` with at least one valid call or `stop` with non-whitespace text. Other finish reasons and an empty `stop` response fail the Run; if the normalized response was persisted, its attempt remains `response_committed` and recovery at `FINAL` repeats the same validation rather than calling the provider again. A malformed normalized response that cannot be committed closes the started attempt as a known `invalid_provider_response` failure.

For `ProviderCallError`, persist the bounded `failure_code`. If `outcome_known` is true, mark `known_failure` and fail with the generic `execution_failed` terminal code. If false, mark `outcome_unknown` and fail with `provider_outcome_unknown`. Any unexpected exception after the claim is conservatively treated as unknown. If persistence fails after a successful response or while writing a failure, leave the committed started marker intact; a later owner must resolve it as unknown, never resend.

### 4. Derive request history only from committed facts

Map the durable state to `ProviderRequest` as follows:

| Durable value | Provider projection |
| --- | --- |
| Run row's `provider` and `model` | Exact `ProviderRequest.provider_id` and `model_id`; never infer from credentials or availability |
| `RunInput.text` | One initial `MessageRole.USER` message; attachments remain unsupported |
| Fixed asset `src/figura/agent/assets/system-v1.md` | One `InstructionBlock(InstructionRole.SYSTEM, ...)`; no user-controlled system prompt |
| `ModelResponseFact` for a tool batch | One assistant message with response content and its calls ordered by `ToolCallFact.position`; attach the matching private continuation on this same message only |
| Each committed `ToolResultFact` | One `MessageRole.TOOL` with its matching `tool_call_id`; serialize the already bounded success result or safe structured error as canonical JSON |
| `project_provider_tools(registry)` | Model-visible function schemas in registry order; handlers and runtime context remain private |
| Agent v1 completion options | `stream=False`, fixed `max_completion_tokens=4096`; leave provider-specific thinking options unset so the selected provider profile retains its current policy |

The builder accepts a model checkpoint only when all preceding call batches have complete results and every historical batch's recorded `registry_version` equals the supplied registry version. An unresolved attempt or unavailable version cannot be represented as a truthful Provider history and therefore fails closed.

For size control, import the Provider boundary's existing request-limit constants and use the same byte accounting for instructions, message text, continuation text, tool-call arguments, tool descriptions, and canonical schemas. When the request exceeds a limit, drop oldest *fully resolved* assistant-plus-tool batches. Always keep the original user message and the newest complete batch. Revalidate the final request with the provider validator before claiming the attempt. If the remaining required history still exceeds a limit, fail the Run without a provider marker or network call. Never truncate a tool result, continuation, call argument, schema, or one side of a call/result pair.

The first request has only the persisted user input. Later requests contain each retained assistant/tool round plus the same original user input. No summaries are synthesized in this change.

### 5. Count limits from durable facts; avoid a second budget store

- Provider request budget: maximum 8 `run_provider_attempts` rows per Run, including the first claim and attempts that end in known failure or unknown outcome. Check before inserting the next row. The attempt's sequence is the authoritative count.
- Tool execution budget: maximum 32 distinct `tool_call_sequence` values with at least one `tool_attempt_started` fact. Multiple attempts for the same logical call count once. The Agent passes `32 - distinct_started_calls` to `DurableToolExecutor.execute_pending(max_calls=...)`; the executor stops after that many new logical calls and returns the current checkpoint. The Agent fails before a subsequent handler if the remaining budget is zero.
- Persist model-returned call intents even if the total pending batch exceeds the remaining execution budget. The Agent may execute only the allowed prefix; it then fails with a bounded `execution_failed` outcome while retaining unstarted intents in the checkpoint. This keeps the provider's accepted response truthful and never exceeds the handler budget.
- Budget failure creates no new provider attempt or tool-attempt start. It uses the current safe generic terminal code rather than adding more public terminal codes.

### 6. Migrate additively and accept legacy committed responses

Bump SQLite `user_version` from 3 to 4 and add only `run_provider_attempts` plus its indexes/constraints. Schema versions 0, 1, and 2 continue through the existing migration steps and then the v3-to-v4 table addition; version 3 applies only the new table. Run the existing SQLite foreign-key and quick checks before committing the migration.

Existing committed model responses predate request-attempt rows. Migration must not invent attempt records or change their continuations. The state reader may accept an initial prefix of legacy model responses without attempt links; after the first v4 provider attempt, every newly committed response must be linked to exactly one attempt. New coordinator writes require the matching started attempt. A v3 Run stopped at a model checkpoint may begin its first recorded attempt after migration; a v3 Run already stopped at a tool checkpoint continues through the same tool recovery boundary.

Validate attempt sequence continuity, unique call history cursor pairs, legal status/null combinations, same-Run response references, response/attempt one-to-one mapping, ordering, and that a started attempt is the last model action and matches the checkpoint. A started attempt may only be terminalized as unknown after exclusive lock acquisition. Reads stay side-effect free.

### 7. Considered alternatives

- **Call Provider directly from `AgentExecutor` without a durable claim:** rejected because a crash after remote dispatch but before response commit would make a second execution indistinguishable from a safe first send.
- **Persist the full request or a separate mutable transcript:** rejected because it duplicates durable Run facts and risks persisting private prompt/tool data. The record and tool-fact prefix already identifies the history used.
- **Retry `started` attempts when replay appears safe:** rejected because model calls have no equivalent of the tool `replay_effect` contract, and identical requests can produce different content or side effects through tools. Unknown outcomes fail the current Run.
- **Add a `waiting` Run status:** rejected for this internal v1. Existing terminal semantics plus a distinct safe terminal code represent the decision without changing Run lifecycle or adding a resume protocol.
- **Persist mutable budget counters:** rejected because attempt rows and tool-start facts are already durable, ordered, and sufficient to derive exact usage.

## Risks / Trade-offs

- [A provider response can be lost between remote completion and local commit] → The durable `started` marker is resolved to unknown and the Run fails; this sacrifices automatic continuation to avoid duplicate remote work.
- [History trimming removes early context] → Only whole oldest resolved rounds are removed, while the original input and newest complete round are retained; fail closed if the required remainder cannot fit.
- [A failed Run can retain pending tool intents after the execution budget is exhausted] → The terminal code and checkpoint remain authoritative, and no over-budget handler is started; later UI/recovery work can present the bounded state.
- [The current tool executor normally consumes a full batch] → Add and regression-test a call-slice limit so a Run budget can stop exactly at its boundary without changing the default behavior for existing callers.
- [Current v3 local databases cannot be opened by the old v3 binary after migration] → Make the v3-to-v4 change additive and transactional; back up the local database before rollout and restore that backup if rolling back to an older binary.
- [Changing provider execution from direct model-checkpoint commits to attempt-bound commits affects internal callers] → Update the coordinator contract and all Figura tests/callers in the same change; the public Gateway/SSE contract remains unchanged.

## Migration Plan

1. Implement the v4 additive migration and read validation while preserving v0–v3 committed Run behavior.
2. Add attempt claim/response/failure/recovery transactions and prove they are compare-and-swap safe before adding the Agent loop.
3. Add request projection, then the checkpoint scheduler and bounded tool slicing.
4. Exercise legacy-schema migration, crash/restart paths, and end-to-end fake-provider tool rounds in focused tests; run the Figura Python test suite and `openspec validate --strict --store figura`.
5. Before updating a user's local v3 store, take a file-level backup. There is no in-place downgrade; rolling back to v3 code requires restoring the pre-migration backup.

## Open Questions

None. The request is intentionally internal and text-only; a production tool catalog and external Run entry point can be planned after this change is complete.
