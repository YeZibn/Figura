## Context

The existing Agent memory already persists model-facing records in SQLite, but
Gateway execution IDs and trace events are managed separately in an in-memory
`RunManager`. The frontend receives a subset of those events through SSE and
keeps them in React state, while the session projection intentionally returns
only completed user and assistant text. Generated visual observations are also
short-lived. See `proposal.md` for the motivation and the delta specs for the
observable contract.

The implementation must preserve the current mock/Gateway client boundary,
the existing trace sanitization rules, the synchronous message endpoint, and
the requirement that Python work uses the Conda environment named `agent`.

## Goals / Non-Goals

**Goals:**

- Give each Gateway run a durable, bounded execution timeline that can be
  queried independently from model conversation messages.
- Use one ordered event shape for initial history, SSE replay, and live events.
- Keep tool calls, results, errors, and visual observations associated by their
  opaque identifiers.
- Let the React client restore and fold execution groups without losing events
  during reloads, session switches, or reconnects.
- Render final answer source text as safe Markdown while retaining a plain-text
  fallback.
- Keep generated visual artifacts authorized, bounded, and removable with the
  owning session.

**Non-Goals:**

- Replacing the existing Agent memory model or adding trace records to the
  model context sent to the provider.
- Requiring a Tauri-only API or changing the desktop launcher lifecycle.
- Inventing intermediate natural-language model output when the provider does
  not return it. Model progress text is displayed only when it is available in
  the provider/runtime event stream.
- Exposing credentials, raw provider responses, unsanitized HTML, hidden local
  paths, or unrestricted provider reasoning.

## Decisions

### 1. Store Gateway execution history separately from Agent conversation memory

Add a Gateway-owned persistence namespace rather than writing trace events into
the existing `records` table. The model context builder consumes `records`, so
putting UI diagnostics there would increase prompt size and risk sending
internal trace data back to the provider.

The SQLite migration creates conceptual tables like:

```text
gateway_runs
  run_id, session_id, status, created_at, updated_at, terminal_code,
  terminal_message, answer_source

gateway_run_events
  run_id, sequence, kind, payload_json, created_at,
  UNIQUE(run_id, sequence)

gateway_run_artifacts
  observation_id, run_id, session_id, managed_path, media_type, caption,
  byte_count, sha256, created_at, expires_at
```

The public Gateway run ID remains distinct from the Agent memory run ID. This
avoids coupling asynchronous HTTP lifecycle state to the internal memory run
that the Agent creates during execution. Session deletion cascades through the
Gateway tables and removes managed artifacts through the existing safe file
store boundary.

Alternative considered: reuse `records` for all trace events. Rejected because
it would pollute model history and mix user-facing conversation data with
transport diagnostics.

### 2. Persist at the Gateway event boundary and keep the in-memory replay cache

`ManagedRun.publish()` continues to notify active SSE subscribers and retain a
bounded in-memory deque for low-latency live delivery. It also writes the
sanitized event to the Gateway event store before notifying consumers. Reads
first use the durable store for sequences not present in memory, so a completed
run remains readable after the process-local retention window.

Persistence failures do not crash an Agent worker. They produce a bounded
run-history warning and leave the live stream usable; the run is marked with a
history-gap state if durable recovery cannot be guaranteed. This preserves the
existing diagnostic isolation principle while making the failure visible.

### 3. Use history hydration plus sequence-based SSE replay

The Gateway exposes run summaries and event history through JSON endpoints. The
SSE endpoint accepts the browser's `Last-Event-ID` and/or an explicit sequence
cursor. The frontend follows this sequence:

```text
load session
  -> load run summaries
  -> load persisted events for each visible run
  -> subscribe to active run SSE with last sequence
  -> merge by (runId, sequence)
  -> refresh terminal summary and answer
```

The client keeps an event map keyed by sequence, sorts only at the normalized
run boundary, and ignores duplicate events. A history-gap response is rendered
as an explicit incomplete state instead of being silently filled with guesses.

Alternative considered: rely only on browser EventSource automatic reconnect.
Rejected because it cannot restore runs after page reload or Gateway restart,
and the current in-memory run may have already expired.

### 4. Model the UI around run disclosures, not a flat message list

The existing user/assistant transcript remains the primary conversation. Each
run is projected into a `RunTimeline` containing a summary and ordered event
rows. A run disclosure owns the small arrow and contains nested event rows;
each tool row uses `call_id` to join call, result, error, and observation
references. The default state is:

- active run: expanded so progress is visible;
- completed run: collapsed so the final answer is primary;
- failed or incomplete run: expanded enough to expose the failure summary.

The collapse state is local UI preference keyed by session and run ID. It is
not part of the Gateway transcript and does not affect event persistence.

### 5. Render Markdown with an allowlisted React pipeline

Store the final answer as source text. Render it through a React Markdown
pipeline with GitHub-style table support and explicit sanitization. Raw HTML,
unsafe URL schemes, unbounded images, and executable attributes are rejected.
The source text remains available for copy/plain-text fallback and tests assert
that rendering does not execute markup.

Alternative considered: inject rendered HTML with `dangerouslySetInnerHTML`.
Rejected because final Agent output is untrusted content and would create an
avoidable XSS boundary.

### 6. Persist generated observations as managed run artifacts

Keep event JSON lightweight by storing only observation metadata and opaque
IDs. Store image bytes in a dedicated managed run-artifact directory with the
same media, size, hash, and session authorization checks used by attachments.
The retention policy can expire old artifacts while leaving the text event and
caption available, which gives the UI a meaningful unavailable-preview state.

Alternative considered: embed observation bytes in SQLite event payloads.
Rejected because it inflates event reads and makes size/cleanup enforcement
harder.

## Risks / Trade-offs

- [Database growth] Durable event histories and overlays can accumulate → apply
  per-event, per-run, per-session, and global artifact limits plus cleanup of
  expired artifacts; keep payloads sanitized before writing.
- [Schema compatibility] Existing session databases are schema version 1 → use
  an additive migration/initialization path, preserve all existing tables, and
  treat old sessions as having no execution history rather than failing open.
- [Trace write latency] Synchronous persistence adds a small cost to each event
  → store bounded JSON in one short transaction and keep the existing in-memory
  event path for active subscribers.
- [Reconnect duplication] History and SSE can overlap at the cursor boundary
  → deduplicate by `(run_id, sequence)` in both Gateway and frontend tests.
- [Expired visual artifacts] Text history may outlive overlay bytes → persist
  captions and metadata, render an explicit unavailable state, and never show a
  broken resource URL.
- [Markdown security] Agent output is untrusted → use sanitization, URL
  allowlists, bounded source length, and tests for script/event-handler payloads.
- [Provider variability] Some providers expose no reasoning or intermediate
  content → show lifecycle/tool evidence consistently and label unavailable
  model content rather than fabricating it.

## Migration Plan

1. Add the additive SQLite schema initialization/migration and verify existing
   sessions, attachments, and transcripts open unchanged.
2. Add Gateway run/event/artifact persistence behind the existing run manager,
   then expose historical run and event reads while keeping current endpoints
   compatible.
3. Update the Gateway adapter and mock adapter to the shared run-history
   contract, including sequence deduplication and explicit history gaps.
4. Update React state and components for run disclosures, correlated tool
   steps, reconnect handling, visual artifact states, and Markdown rendering.
5. Run migration and cleanup tests, Gateway API tests, React build/smoke tests,
   and an end-to-end reload/reconnect acceptance test.

Rollback is additive: an older client can continue using completed transcript
and existing SSE endpoints, while the new Gateway tables and managed artifact
files remain unused until the upgraded client is deployed again.
