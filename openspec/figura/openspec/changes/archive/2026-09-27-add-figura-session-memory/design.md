## Context

See `proposal.md` for motivation and `specs/` for the required behavior. The current implementation already stores each Run's immutable input, model responses, tool facts, provider attempts, and final-answer reference. `AgentRequestBuilder` currently projects only one `RunState`; it also removes the oldest complete tool rounds when a request exceeds limits. SQLite schema version 5 has no Session-wide message table, and attachment deletion is already prevented while an immutable Run input references the image.

## Goals / Non-Goals

**Goals:**

- Make same-Session Run facts the only source for complete conversation history.
- Give the Memory projection explicit ownership, fields, ordering, and conversion boundaries.
- Keep Provider validation and attempt-claim ordering fail-closed.
- Make Session Run order stable even when two callers create Runs concurrently.

**Non-Goals:**

- Persisting a second message transcript, summaries, embeddings, cross-Session memory, or editable memory records.
- Retention, token budgeting, pruning, summarization, or Provider request splitting.
- Changing Run input fields, attachment storage fields, Provider request fields, or the SQLite schema version.
- Changing per-Run Provider-attempt and tool-call budgets.

## Decisions

### 1. Run facts remain authoritative; Session history is a read model

Do not add a `session_messages` table or fields to `Run`, `RunInput`, or execution records. Each historical user message comes from its `RunInput`; assistant messages come from `ModelResponseFact`; tool calls and observations come from `ToolCallFact` and `ToolResultFact`. `FinalAnswerFact` is only a reference to an existing model response and does not add a second message. This avoids dual writes and lets the existing append-only facts remain the recovery source.

The persistence boundary should expose a Session-scoped query for validated `RunState` aggregates preceding a target Run. It must validate that the target Run belongs to the requested Session, filter strictly by `ordinal < target.ordinal`, return rows in ascending ordinal, and read the selected aggregates in one SQLite read transaction. The query adds no persistence fields or migrations.

### 2. Put provider-neutral projection values in `src/figura/memory/`

The Memory package owns immutable, transient projection values. It does not own SQLite, attachment bytes, Provider request types, or execution writes.

| Projection | Fields | Source and meaning |
| --- | --- | --- |
| `SessionHistory` | `session_id`, `target_run_id`, `target_run_ordinal`, `messages` | Identifies the authorized Session and target boundary. `messages` contains only lower-ordinal Runs. |
| `UserMessage` | `run_id`, `run_ordinal`, `source_record_id`, `text`, `attachment_ids` | One `RunInput`. Attachment IDs retain the input order; bytes are not stored in Memory. |
| `AssistantMessage` | `run_id`, `run_ordinal`, `source_record_id`, `content`, `tool_calls` | One committed `ModelResponseFact`. It includes normalized assistant text and any ordered calls. It has no continuation field. |
| `MemoryToolCall` | `call_id`, `tool_name`, `arguments_json`, `position`, `registry_version` | One `ToolCallFact`; preserves provider order and the registry version needed for compatibility checks. |
| `ToolMessage` | `run_id`, `run_ordinal`, `source_tool_sequence`, `tool_call_id`, `content` | One committed `ToolResultFact`, encoded as the same bounded JSON observation already used by Agent requests. |

Use a closed role-specific message union rather than a bag of nullable fields. `UserMessage` may carry attachment IDs; `AssistantMessage` may carry tool calls; `ToolMessage` carries its matching call ID. Source Run and record/tool sequence values provide provenance; no new message ID or creation timestamp is needed because source facts already identify and order each message.

`SessionMemoryProjector` is pure: it accepts validated prior `RunState` values and returns `SessionHistory`. It does not mutate facts or retain a process-wide cache. The projection omits lifecycle events, attempt metadata, final-answer references, and continuation payloads because none of those are cross-Run conversation messages.

### 3. Keep persistence, projection, and Provider conversion in separate owners

- `RunRepository` loads earlier `RunState` aggregates from existing tables and enforces Session ownership and ordinal bounds.
- `FiguraRunStore` and `RunCoordinator` expose the internal read operation without exposing SQL to Agent code.
- `SessionMemoryProjector` maps validated Run facts into `SessionHistory` and role-specific messages.
- `AgentRequestBuilder` converts projected values to `ProviderMessage`, resolves every `attachment_id` through `FiguraAttachmentService` using the same `session_id`, combines prior history with the current Run's input and committed prefix, and validates the entire request.
- `AgentExecutor` continues to claim a Provider attempt only after request assembly and validation succeed.

The current Run's request history remains assembled from its current `RunState`, which preserves same-Run provider continuation behavior. The builder prepends `SessionHistory.messages`, then appends the current Run's input and complete committed response/tool-result prefix. It sends the fixed system instruction once, for the current Provider call; historical Runs do not add copies of system instructions.

### 4. Project facts in deterministic conversation order

1. Sort prior Runs by `Run.ordinal` ascending.
2. For each Run, emit its input as one user message.
3. Visit model responses by `record_sequence`. Emit one assistant message for each response, including normalized assistant text and all calls for that response sorted by `ToolCallFact.position`.
4. Immediately after each assistant tool-call message, emit one tool message per call in that same position order. Convert success and failure results with the existing bounded JSON observation format.
5. Do not emit `FinalAnswerFact` separately because it points to the existing assistant response.
6. After all prior Runs, append the current Run's input and committed response/tool prefix using the existing current-Run projection. Only current-Run assistant messages may receive their persisted provider-private continuation.

`ToolAttemptStartedFact` is execution metadata, not a conversation message. If a historical call has no committed result, or a response's batch cannot be matched one-to-one with its results, reject the whole request before Provider-attempt claim. Never synthesize an observation or omit only the invalid interaction.

### 5. Enforce one active Run inside the Run-creation transaction

`RunRepository.create_initial_run` already opens a SQLite `BEGIN IMMEDIATE` transaction and rechecks the idempotency mapping there. Keep the order:

1. Verify Session existence.
2. Recheck idempotency; return the matching Run or raise the existing idempotency conflict.
3. Check whether the Session has any Run with `status = 'running'`; if so, reject with the existing bounded `INVALID_TRANSITION` error.
4. Validate attachment ownership, assign the next ordinal, and commit the new Run facts atomically.

The idempotency check must precede the active-Run check so retrying the same create request returns its original active Run. `BEGIN IMMEDIATE` makes distinct concurrent creates serialize at the authoritative storage boundary; a frontend-only disabled button is not sufficient.

### 6. Keep full history and apply only existing Provider hard limits

Remove the loop that pops prior rounds from `AgentRequestBuilder`. Build the full request and run the existing Provider request validator before claiming an attempt. Current hard bounds include 256 messages, 32 instruction blocks, 64 tool definitions, 1 MiB aggregate text/schema bytes, 16 images, 24 MiB minus 64 bytes per image, and 32 MiB aggregate image bytes. Use the constants and validator as the authority rather than copying numeric limits into Memory.

Any hard-limit, invalid-history, attachment-resolution, or integrity failure returns through the existing bounded Run error path before `begin_provider_attempt`; it does not delete or modify history. Provider-attempt and tool-call budgets remain per Run as currently specified.

### 7. No schema migration or API payload change

This change adds only query and projection behavior. Keep schema version 5 and all current durable records unchanged. Run creation requests and Provider requests keep their current fields. A distinct overlapping Run creation uses the existing `INVALID_TRANSITION` response contract; an exact idempotent replay still returns the original Run.

## Risks / Trade-offs

- **Complete history eventually exceeds Provider hard limits** → Preserve every fact and fail before Provider-attempt claim as requested; later continuation in that Session requires a separately approved strategy.
- **A prior Run contains an unresolved tool attempt or incomplete batch** → Fail closed instead of inventing a result or sending malformed history; durable recovery remains owned by the existing tool-execution capability.
- **A Provider registry changes between Runs** → Reuse the existing registry-version compatibility check for historical calls and fail closed when the current registry cannot safely interpret them.
- **One active Run per Session rejects overlapping submissions** → Enforce it in the SQLite creation transaction and preserve exact idempotent retries; this is the ordering guarantee that makes full Session history deterministic.
- **Loading full prior Run aggregates grows with Session length** → Do not introduce a hidden retention cap. Use one ordered read snapshot and project only conversation facts; Provider hard limits bound the final dispatchable request.

## Migration Plan

1. Add the read-only prior-Run query and provider-neutral projection without changing schema version 5.
2. Add the transactional one-active-Run check while preserving idempotency lookup semantics.
3. Integrate `SessionHistory` into Agent request construction, remove truncation, and retain pre-claim validation.
4. Run focused Memory, Run-creation concurrency, attachment, Provider-boundary, and Agent request tests, then the full Figura test suite.

Rollback is a code rollback only: there are no new tables or persisted fields to migrate. The previous implementation can read all existing Run facts, though it will again construct only current-Run history and may trim old same-Run rounds.
