## Context

See `proposal.md` for motivation and `specs/` for behavior contracts. Today `AgentRequestBuilder` projects all earlier Run messages plus the current Run into one `ProviderRequest`; the provider client estimates the serialized prepared payload only after the request has been assembled. `RunExecutionStateService` reconstructs a complete same-Session resource catalog, while the Prompt layer serializes a locator-oriented projection of that catalog. `RunExecutionImageReader` can resolve image references, but the current model-facing image tool only accepts Attachment and Panel IDs.

The implementation must preserve complete `RunState` records, tool facts, resource reconstruction, provider continuations, Run retry bindings, and the existing payload/protocol guards. A compaction result may change only the request projection and must remain traceable to those canonical sources.

## Goals / Non-Goals

**Goals:**

- Reuse the existing local request estimator and configured model capacity to decide when an extra summary request is warranted.
- Keep summary source coverage, Run prefix, and ordinary Provider retry reconstruction durable and deterministic.
- Let the model locate and retrieve exact historical messages, committed tool results, outcome records, and authorized images without replaying old tools.
- Keep the full resource catalog available to server-side consumers while sending a smaller locator projection to the model.

**Non-Goals:**

- Replacing or editing canonical Run facts, deleting old messages, or adding a cumulative Run output/token budget.
- Adding vector embeddings, a vector database, a user-facing summary report, or new output truncation limits.
- Changing tool execution semantics, Provider retry policy, resource ownership, or image integrity rules.

## Decisions

### Keep canonical facts authoritative and store only a derived summary checkpoint

Add a Session-scoped context checkpoint in the existing durable store. It contains the generated summary, source references, covered-history frontier, revision, and the summary contract/version needed to validate reuse. It contains no copy of raw messages, tool results, continuations, or image bytes. The checkpoint is a replaceable projection: on corruption or absence, Figura can rebuild from Run facts; source references are checked against the same Session before use. Updating a checkpoint is atomic and tied to the source frontier it covers. Session deletion removes its checkpoint.

This avoids inserting summaries as fake user/assistant messages, which would alter provider role history and call ordering. Keeping summaries only in process memory was considered, but would repeat model calls after restart and between Runs. A second authoritative transcript was rejected because Run records and tool facts already own those values.

### Run compaction as a durable internal Provider operation before the ordinary attempt

Keep `AgentRequestBuilder` responsible for building a canonical uncompressed projection. The Agent execution coordinator then prepares that request through the selected `ProviderClient`, reads the exact local estimate and configured capacity, and checks the 80% trigger before it claims the ordinary Provider attempt.

When compaction is due, a context-compaction service selects the oldest eligible closed interactions up to a complete source frontier, combines any prior checkpoint with that source slice, and builds a tool-free summary request for the same selected Provider/model. The response is validated for schema, source references, and outcome classifications before an atomic checkpoint update. The service rebuilds and re-prepares the ordinary request from the new summary plus recent raw history, then targets approximately 50% occupancy where the protected current input and tail allow it.

The summary operation is recorded as an internal Provider operation with a stable source frontier and request identity; its response is not committed as an assistant conversation message or surfaced as a user report. It uses the current Provider retry, timeout, and interruption handling. The ordinary request binding records the projection/checkpoint revision and the compaction decision, so a later Provider retry reconstructs the exact same payload and does not unexpectedly run a new summary operation. A failed summary leaves the previous checkpoint unchanged and records a fallback decision; the ordinary request proceeds with the uncompressed projection when existing validation permits it.

An alternative was to make the model choose when to call a summarization tool. That would not meet the accepted threshold-triggered behavior and would consume a tool round in the user conversation. Generating a summary inside the ordinary response was also rejected because that response cannot both reliably continue the task and return a separate validated compaction artifact.

### Compact only old closed interactions and keep incomplete outcomes explicit

Select a contiguous oldest prefix of complete interactions. Never split an assistant response from its tool calls/results, and never move a summary boundary through an incomplete abnormal tail. Retain the active Run input, required current Run prefix, and recent raw tail. The summary includes source refs for claims and explicit source-linked statuses for any abnormal outcomes it covers. If protected context prevents reaching the target, use the best safe projection and do not delete required content.

The existing full `RunExecutionState` remains unchanged. Prompt assembly uses the complete state to form a lightweight locator projection containing resources relevant to the active Run, recent raw history, or summary references. Older resource metadata remains discoverable through history search. This keeps a growing catalog from defeating message compaction while preserving complete server-side `.list()` and `.get()` behavior.

### Separate discovery from exact reads

Add a read-only Session history service that consumes validated prior `RunState` values and the target Run's committed prefix. It derives message and tool-result candidates from canonical records/facts, and resource candidates from the existing typed execution catalog. The first implementation uses summary references, source metadata, and local text matching; it does not introduce a durable search index or embeddings. A future index can replace the matching implementation without changing the tool contract.

Expose separate model-facing operations:

- `search_history` accepts a query and optional source/Run filters; it returns source references, Run ordinal, role/tool/outcome metadata, identifying excerpts, and a continuation cursor.
- `read_history` resolves a message reference, generic tool-result reference, or typed resource reference to the exact original content. An optional selector narrows a large result; without one, it returns the selected source item completely under existing payload rules.
- `read_resource_image` passes an authorized typed resource reference to `RunExecutionImageReader` and attaches the verified image through the existing Provider image-input observation path. The existing `load_image` interface remains compatible.

Message references use the originating `run_id` and record ID; generic tool-result references use the originating `run_id` and logical call ID; specialized resources reuse `ImageResourceRef` and `ToolResourceRef`. A cursor is bound to the calling Session and target Run prefix. Tool context supplies Session identity; model arguments cannot select another Session. Search results are deliberately excerpts and references rather than full documents so the model explicitly chooses what to read.

Search/read tool calls follow the normal current-Run audit and replay-safe execution path. Returned content is marked untrusted. Old tools are never re-executed. A read result is part of the current Run's durable tool interaction; subsequent request compaction may summarize that interaction while its original source remains readable. This keeps the retrieval action auditable without making the copied result a new source of truth.

### Keep local estimation approximate and non-blocking

Use the existing serialized-request estimator and its configured `context_window_tokens`; do not add a second token-counting mechanism. Evaluate the threshold against the full prepared ordinary request, including instructions, tool schemas, active messages, images, and the locator projection. If capacity or estimate is absent, do not auto-compact. Re-estimate after compaction. The estimate may trigger only this context projection operation; it cannot become an admission check, output reservation, Run budget, or reason to truncate history.

## Risks / Trade-offs

- **Generated summaries omit or distort facts** → Require source references, preserve canonical facts, and expose exact read tools; reject malformed or ungrounded summary output.
- **Retrieved text contains prompt injection** → Label all historical content and summaries as untrusted source data in tool results and Prompt instructions.
- **Extra Provider operation adds latency and cost** → Trigger only at the configured threshold, compact only new eligible source coverage, and reuse the durable checkpoint across requests and Runs.
- **A crash occurs after the summary Provider responds but before checkpoint commit** → Keep the operation read-only and retry-safe; commit the validated result atomically. A repeated summary call may incur cost but cannot duplicate a user-visible action or mutate Run facts.
- **Lexical discovery misses a paraphrased topic** → Retain source-linked semantic summary entries as the primary navigation map and allow filters/continuation; defer embeddings until observed retrieval misses justify them.
- **Resource locator projection grows with Session size** → Include active/recent and summary-referenced resources in the request; discover older resources through search while retaining the complete server-side catalog.
- **Retrieval duplicates old content in the current Run record** → Store the retrieval as a normal auditable tool interaction, then allow later request compaction to replace old retrieved payloads with a source-linked summary; canonical original facts remain authoritative.

## Migration Plan

1. Add the nullable context-checkpoint storage and internal compaction-operation metadata without changing existing Run or resource records. Existing Sessions start with no checkpoint and continue to reconstruct from canonical facts.
2. Add source-reference validation, history search/read services, and image-resource retrieval; register tools without changing the existing `load_image` arguments.
3. Add request projection support for a validated checkpoint and protected recent tail, while keeping a canonical uncompressed builder path for fallback and compatibility checks.
4. Integrate threshold evaluation and summary operations before ordinary Provider-attempt claim; persist the chosen projection identity in request bindings so retry fingerprints stay stable.
5. On rollback, ignore the checkpoint and internal compaction metadata and use the canonical history projection. Do not delete Run facts or require a data migration for existing Sessions.

## Open Questions

None. Search ranking and any future persistent text index can evolve behind the specified search/read contract without changing this change's behavior.
