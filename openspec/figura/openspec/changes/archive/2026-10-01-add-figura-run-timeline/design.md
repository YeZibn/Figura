## Context

See `proposal.md` for the motivation and capability scope. Figura already persists the authoritative Run tool facts and checkpoint transitions. Its event stream currently contains only Run lifecycle events, while the React workspace already has a flat timeline presentation for legacy ChartAgent event payloads. The new view must project Figura's own facts without translating them into fabricated ChartAgent events.

`RunExecutionImageReader` already reconstructs OCR and measurement overlays from committed results and their authorized attachment or Panel sources. Attachment, Panel, and ChartRender images also have existing Session-scoped content reads.

## Goals / Non-Goals

**Goals:**

- Present a persisted Run as one chronological row per tool call, with attempt and outcome information grouped under that row.
- Refresh an active timeline from replayable progress markers and restore it from committed facts after reload.
- Expose only user-facing allowlisted summaries; keep provider and raw tool payloads inside Python.
- Reuse existing image readers and content routes, with OCR and measurement overlays reconstructed only when requested.

**Non-Goals:**

- Persist a second timeline table, duplicate tool facts, or store reconstructed observation PNGs.
- Change Agent tool choice, measurement scope selection, tool retry/replay policy, or Run recovery behavior.
- Add timeline rows for provider model turns, or move Panel and ChartRender galleries into the timeline.
- Change ChartAgent or mock event contracts.

## Decisions

### 1. Derive timeline rows from committed tool facts

The Runtime `ToolCallFact` is the row identity and ordering source. Group `ToolAttemptStartedFact` and `ToolResultFact` by `call_id` and `tool_call_sequence`; order rows by the call fact's durable tool sequence. The Run ID and call ID together form the client merge key. A read never writes facts, schedules execution, or replays a tool.

This reuses the existing durable execution model and avoids a second state machine that could disagree with the checkpoint. A separate timeline record or synthetic lifecycle event per tool was considered and rejected because it would duplicate the source of truth and enlarge persisted payloads.

### 2. Use a minimal durable `run_progress` marker

Add `run_progress` to the durable Run event kinds. Append one marker in the same SQLite write transaction whenever that transaction adds a tool call batch, starts an attempt (including a replay attempt), or commits a result. A batch of calls created by one model response gets one marker. A text-only model response gets none. The payload contains only `checkpoint_revision`; tool name, arguments, result, error, observation, and provider data stay in their existing records.

The Runtime event codec, persistence helpers, and Run-state validator must accept progress events between the initial creation event and the optional terminal event. Creation remains the first event, event sequences remain contiguous, and a terminal event remains the final event. Existing Runs with only lifecycle events remain valid without rewriting their rows.

The Gateway publishes the marker under the existing `runId:sequence` SSE identity. The client treats it as a refresh signal and reads the timeline snapshot; it does not construct a timeline row from event data. Polling was considered but rejected because it adds repeated reads and cannot provide a durable reconnect cursor. Putting tool summaries in the SSE marker was rejected because it duplicates payloads in the event log.

### 3. Return a safe snapshot and lazy per-call details

Add these Session-scoped reads alongside the existing Run history route:

- `GET /api/v1/sessions/{sessionId}/runs/{runId}/timeline` returns `{runId, steps}`. Each summary contains `callId`, `toolSequence`, `toolName`, `createdAt`, `updatedAt`, `status`, and a short `summary`.
- `GET /api/v1/sessions/{sessionId}/runs/{runId}/timeline/{callId}` returns that call's `argumentSummary`, `resultSummary`, attempt history, safe error summary, optional typed source reference, and whether an observation preview is available. It does not return `arguments_json` or raw result JSON.
- `GET /api/v1/sessions/{sessionId}/runs/{runId}/timeline/{callId}/observation` returns a validated PNG only for a successful OCR or measurement result that has an authorized source.

All IDs are resolved against the requested Session and Run before returning data. A call that is not found in that Run returns the same bounded not-found response as other private Run resources. The observation route uses `RunExecutionStateService` and `RunExecutionImageReader`; it verifies the tool resource and source, reconstructs the overlay in memory, and responds with `image/png`, `Cache-Control: no-store`, and `X-Content-Type-Options: nosniff`. For `load_image`, the detail response points to the existing attachment or Panel content route instead of creating another image endpoint. Rendered charts and Panels remain in their existing galleries.

Known current tools receive small tool-specific display projections: source name/reference and dimensions for image reads; Panel count/names for decomposition; OCR snippet count and availability; measurement type and bounded result summary; Figure title for assembly; and Figure title/dimensions for render. A bounded failure code is mapped to safe display text. Unknown tool names expose only the stable tool identifier, status, and timestamps. Arbitrary arguments and results are never serialized to the browser.

Call status is derived only from committed facts and dispatcher ownership:

| Durable facts and Run state | Timeline status |
| --- | --- |
| No attempt; Run is running | `pending` |
| Latest attempt has no result; Run is running and this Gateway's dispatcher owns it | `running` |
| Latest attempt has no result; Run is running and the dispatcher does not own it | `needs_reconciliation` |
| Attempt has no result; Run is terminal | `unknown` |
| Committed successful result | `completed` |
| Committed failed result | `failed` |
| No attempt; Run is terminal | `not_started` |

Add a locked `RunDispatcher` ownership query for the Gateway projection. The dispatcher is the only basis for presenting an unresolved attempt as actively running; reads do not acquire locks or change checkpoints. Unsupported or inconsistent facts fail closed as unknown/integrity errors and are never presented as success.

### 4. Reuse the visual pattern without fabricating legacy events

Figura mode gets a DTO-to-view-model mapper and renders the same concise interaction pattern as the legacy timeline: one flat row per tool call, localized tool label when known, status and time visible, and safe detail collapsed by default. Expanded details load only for that row. The implementation may reuse presentational primitives from `RunTimeline`, but it must not synthesize `AgentRunEvent` values or pass Figura data through the legacy correlation algorithm.

The client loads the timeline snapshot when a Figura Run is opened or expanded. A `run_progress` event refreshes the current Run's snapshot and preserves the durable event cursor. Expansion state is keyed by `(runId, callId)`. The detail and observation requests happen only when the user expands a row. On reconnect, SSE replays markers after the saved sequence and each marker triggers a snapshot refresh; the call identity prevents duplicate rows.

### 5. Migrate the event-kind constraint without rewriting event history

SQLite currently constrains `run_stream_events.event_kind` to the four lifecycle values. Increase the Figura schema version and rebuild only this table with `run_progress` added to its allowlist. Copy every existing row with its original event sequence, kind, payload, and timestamp; recreate the event immutability triggers; run the existing foreign-key and quick checks before committing the migration. Fresh stores use the expanded constraint directly. The Runtime continues to accept lifecycle-only histories without synthesizing progress markers.

This is a data-preserving constraint migration, not a second event format or compatibility alias. Once a store contains `run_progress` rows, an older Figura binary that does not recognize that event kind cannot read the store; local downgrade therefore requires restoring a pre-change `.figura` backup or resetting disposable development data.

## Risks / Trade-offs

- **[A tool fact or progress marker is committed without its pair]** → Insert the marker, facts, and checkpoint update in the same transaction; add rollback and replay coverage at each commit site.
- **[A live attempt is shown as stuck or falsely complete]** → Derive success only from `ToolResultFact`; use a synchronized dispatcher ownership query for `running`; show reconciliation/unknown for unresolved attempts outside that ownership.
- **[Details leak prompt data, local paths, or large results]** → Use per-tool allowlisted summaries, bounded strings, safe error codes, and a generic fallback for unknown tools; never return raw argument/result JSON.
- **[A preview points to a different or uncommitted source]** → Resolve source references through the selected Session and Run's reconstructed resource catalog, and reuse existing image validation before responding.
- **[An event-table migration drops or alters existing history]** → Rebuild the table inside the existing migration transaction, copy all event columns verbatim, and verify preserved rows plus `foreign_key_check` and `quick_check` before commit.
- **[Older development data cannot be read after downgrade]** → Document the event-kind compatibility boundary and restore a pre-change store backup before running older code.

## Migration Plan

1. Extend the Runtime event kind and strict codec, migrate the event-kind constraint from the current schema, add atomic progress markers, and update state validation while preserving lifecycle-only Run histories.
2. Add the Gateway projections, lazy details, observation read, and dispatcher ownership query with Session/Run scope checks.
3. Add Figura client types and API methods; subscribe to `run_progress` without changing ChartAgent or mock adapters.
4. Render the Figura timeline using the safe projection and existing collapsed-row visual pattern; keep Panel and ChartRender galleries separate.
5. Run targeted Runtime/Gateway tests, frontend build and smoke checks, then `git diff --check`.

Rollback is a code-and-store operation. If the new event kind has been persisted, restore the pre-change `.figura` store backup before starting an older binary. The normal upgrade path does not rewrite or migrate existing Run rows.
