## Context

See `proposal.md` for motivation and `specs/` for the behavior contract. The Provider layer already returns a private `ProviderContinuation` with provider identity and format version. `RunCoordinator._model_response_fact` currently rejects it; the run record codec only reads model-response payload version 1; SQLite is at schema version 2; and `RunState` reconstructs core records and tool facts but no continuation data. Model response, tool-call facts, and checkpoint already share one SQLite write transaction.

The continuation can be larger than the 256 KiB core-record JSON limit, so its raw content must not be embedded in the core record JSON. Existing provider response normalization allows up to 1,048,576 characters, while the Provider request validates aggregate text as UTF-8 bytes against a 1 MiB limit.

## Goals / Non-Goals

**Goals:**

- Persist the exact provider-private continuation beside the Run and originating model response, with an opaque reference in the normalized model-response fact.
- Commit or reject the whole model-response transition as one unit, including continuation, ordered tool calls, and checkpoint.
- Reconstruct the same private continuation after restart and validate all references before returning internal Run state.
- Keep existing v1 model-response records readable and migrate SQLite additively.
- Retain continuation data for the full Run lifecycle, including terminal Runs.

**Non-Goals:**

- Implement the Agent ReAct loop, prompt/history selection, model-turn limits, or context-window pruning. A later Agent change consumes the private RunState data and owns request assembly.
- Journal Provider request attempts or resolve unknown remote outcomes. This change starts only after a normalized response has been received.
- Add public APIs, Gateway/SSE fields, CLI/UI controls, retries, fallback, or new provider behavior.
- Add encryption or key management for SQLite at rest. Continuation data uses the existing local Run-store access boundary; this design makes no encryption guarantee.

## Decisions

### Store raw continuation separately and reference it from the model response

Add a private typed continuation record in the runtime model layer. Persist its raw `reasoning_content` in a dedicated `run_provider_continuations` SQLite table, separate from the size-limited core record JSON. Add `continuation_ref: str | None` to `ModelResponseFact`; new model-response payloads use schema version 2 and carry the opaque reference. Store the continuation row with `run_id`, `response_record_id`, `provider_id`, `format_version`, continuation `schema_version`, raw content, and creation time. Enforce one continuation per `(run_id, response_record_id)`, a composite reference to the originating Run record, and model-response kind validation. The table is append-only and has no consumption/deletion operation.

Alternatives considered: embedding raw reasoning in `ModelResponseFact` would couple private data to the 256 KiB core-record limit and broaden accidental serialization exposure; storing only a ref without a durable payload would not support restart recovery.

### Version model-response facts independently from the SQLite schema

New model-response facts use payload schema version 2 and include an optional `continuation_ref`, including when the value is null. The SQLite record `schema_version` for those rows is 2. The codec continues to decode existing version 1 rows and decodes version 2 only for `model_response`; input/final-answer records remain version 1. Unknown versions fail closed. A missing or extra field for the declared version is an integrity error.

Alternatives considered: changing the SQLite table shape to add a continuation-reference column would duplicate the reference already carried by the typed record and require a broader row migration. Rewriting v1 records would violate their immutable history and add no recovery value.

### Commit response, private continuation, tool calls, and checkpoint atomically

`RunCoordinator` validates that a continuation is a `ProviderContinuation`, matches the response and Run provider, uses supported format version 1, has nonempty valid UTF-8 content, and meets the byte limit. The coordinator creates the opaque response ID and, when needed, continuation ID; it puts the continuation reference on the v2 model-response fact and passes the private ProviderContinuation plus its ID to `FiguraRunStore.commit_model_response`. The store revalidates the cross-references and creates the durable typed continuation fact with the transaction timestamp. In the existing write transaction, it inserts the response record, optional continuation row, ordered tool-call facts, and updated checkpoint. Any size, uniqueness, state, or storage failure rolls back the complete transition. A response without continuation writes no continuation row and stores a null reference.

The initial per-continuation limit is **512 KiB UTF-8**. This is a provisional plan choice: it leaves room below the existing 1 MiB aggregate Provider request-text budget and keeps one private durable payload bounded. The implementation SHALL reject rather than truncate. No aggregate per-Run continuation limit is added here; a later Agent ReAct change owns model-turn and assembled-history budgets.

Alternatives considered: committing the response first and continuation afterward would allow a checkpoint to reference missing history; truncation would change provider-owned opaque data and make replay invalid.

### Reconstruct continuations only in internal Run state

Extend `RunState` with an internal tuple/map of typed continuation records hidden from `repr`. `_read_run_state_from_connection` loads the continuation rows and `_validate_state` checks a bijection between non-null response references and rows: same Run, model-response ID, provider, and format version; no orphan rows, duplicate references, missing payloads, or unsupported versions. Existing v1 response records legitimately have no continuation. Any inconsistency fails the entire Run read with a bounded integrity/version error. Reading state does not change the checkpoint or call a Provider/ToolRuntime.

The future Agent history assembler uses the response-record association to put the exact provider continuation back on the matching assistant message. This change does not decide which older turns are retained in a prompt. Public Run projections, events, ordinary logs, traces, errors, and `repr` continue to omit payload and reference.

Alternatives considered: a separate lookup for each response would introduce repeated storage reads and allow callers to assemble partial state without the RunState integrity check; a public continuation endpoint would expose provider-private data beyond the trusted execution boundary.

### Add SQLite schema version 3 without rewriting existing facts

For a fresh store, create the continuation table and append-only triggers with the current schema. For schema version 2, create only the new table/triggers, validate foreign keys and `quick_check`, then set `user_version` to 3 in the same migration transaction. For version 1, run the existing v1-to-v2 tool-fact migration and then the v2-to-v3 continuation migration before committing. Existing Runs, records, tool facts, checkpoints, events, idempotency mappings, and opaque IDs are not rewritten. The migration does not backfill continuations for older responses.

Rollback is by restoring the pre-migration database backup: a binary that only supports schema version 2 rejects a version 3 database, and this change does not implement a destructive downgrade.

Alternatives considered: rebuilding the core record table is unnecessary and risks immutable history; lazy table creation would make schema correctness depend on the first continuation write.

## Risks / Trade-offs

- **Continuation content is sensitive and stored in local SQLite** → keep it in an internal append-only table, hide it from repr/public projections/logs/errors, use session-scoped Run ownership checks, and rely on the existing local-store access boundary. No at-rest encryption is claimed; changing that requires a separate key-management contract.
- **A Run can accumulate multiple bounded payloads** → enforce 512 KiB UTF-8 per payload and leave model-turn/history budgets to the Agent ReAct change; do not delete a payload after replay because the user chose Run-lifetime retention.
- **Reference or migration corruption can make a Run unreadable** → validate both the model-response reference and continuation row on every state reconstruction, fail closed, and keep all migration steps transactional.
- **Model-response codec changes can break old Runs** → retain strict v1 decoding, use v2 only for new response payloads, reject unknown versions, and cover v1/v2 round trips in planned tests.
- **A valid response can exceed the durable continuation bound** → reject before any transaction writes and report a bounded storage-contract error; never truncate or commit the response without its continuation.

## Migration Plan

1. Add the private continuation type, response payload v2 codec, strict v1 compatibility, size validation, and store/state invariants.
2. Add the schema v3 table, indexes/constraints, append-only triggers, and transactional version 0/1/2 initialization paths.
3. Wire `RunCoordinator` to validate and pass the Provider continuation into one atomic `commit_model_response` transition.
4. Verify fresh-store creation, v1-to-v3 and v2-to-v3 migrations, rollback on migration failure, old v1 reads, v2 continuation reads after reopen, and privacy projections.
5. Before deploying a release that opens stores at schema v3, preserve a database backup. Rollback to a schema-v2-only binary requires restoring that backup.

## Open Questions

None for the selected storage and transaction approach. The 512 KiB per-continuation limit and the absence of new at-rest encryption are explicit plan boundaries to review before implementation; changing either requires updating this design and the matching implementation record.
