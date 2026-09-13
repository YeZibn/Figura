## 1. Contracts and Persistence Foundation

- [x] 1.1 Define shared Gateway run-summary, execution-event, history-gap, and run-artifact protocol shapes with bounded fields and explicit terminal states.
- [x] 1.2 Add an additive SQLite schema migration for Gateway-owned runs, ordered events, and managed visual artifacts without changing model-context records.
- [x] 1.3 Implement durable event writes at the sanitized Gateway event boundary while retaining the bounded in-memory replay cache and isolating persistence failures.
- [x] 1.4 Add retention limits, cleanup, ownership checks, and session-cascade deletion for persisted events and visual artifacts.

## 2. Gateway History and Streaming

- [x] 2.1 Extend the Gateway service with run-summary and historical-event reads scoped to a session and opaque run ID.
- [x] 2.2 Update the SSE route to replay durable events after `Last-Event-ID` or an explicit cursor, then follow active in-memory events without duplicates.
- [x] 2.3 Persist generated visual observations through a managed run-artifact store and serve them through authorized session/run-scoped references.
- [x] 2.4 Preserve the synchronous message endpoint and completed transcript behavior while exposing incomplete or failed run history separately.
- [x] 2.5 Add bounded history-gap, unavailable-run, event-persistence-warning, and artifact-expired responses without leaking local paths or provider data.

## 3. Client Protocol and State Model

- [x] 3.1 Extend frontend protocol types and the client boundary with run summaries, historical events, history gaps, and artifact availability.
- [x] 3.2 Implement Gateway adapter methods for run history hydration, cursor-based event recovery, and authorized observation URLs.
- [x] 3.3 Normalize live and historical events by `(runId, sequence)` and correlate tool call, result, error, and observation records by `call_id`.
- [x] 3.4 Update session loading, session switching, and active-run lifecycle so persisted execution groups are retained instead of being replaced by the next `liveItems` array.
- [x] 3.5 Update the mock adapter to emit the same normalized event categories and run-history shape for offline UI testing.

## 4. React Execution Timeline and Markdown Answer

- [x] 4.1 Add a run-level disclosure component with status, event count, timestamps or duration, keyboard-accessible arrow control, and stable expanded/collapsed state.
- [x] 4.2 Add ordered event rows for model boundaries, progress when available, tool calls, results, failures, budget termination, and visual observations.
- [x] 4.3 Render each tool call as one correlated step whose running, success, or error state updates when the matching result arrives.
- [x] 4.4 Add safe Markdown rendering for final answers with headings, lists, tables, links, emphasis, fenced code, bounded source text, and plain-text fallback.
- [x] 4.5 Render reconnecting, history-gap, interrupted, unavailable-observation, and persistence-warning states without removing prior events.
- [x] 4.6 Keep the timeline usable at narrow widths and with keyboard navigation, and preserve the current Simplified Chinese Figura visual language.

## 5. Automated Coverage

- [x] 5.1 Add Python tests for schema migration, event ordering, durable replay after in-memory expiry, payload sanitization, retention cleanup, and session deletion cascades.
- [x] 5.2 Add Gateway service and HTTP tests for run history, SSE cursor replay, duplicate boundaries, history gaps, artifact authorization, and synchronous compatibility.
- [x] 5.3 Add frontend/client tests or deterministic smoke assertions for event normalization, call correlation, Markdown safety, disclosure behavior, reload hydration, and reconnect recovery.
- [x] 5.4 Add an end-to-end acceptance scenario that starts a Gateway run, reloads the session, expands the persisted execution trace, and verifies the Markdown final answer.

## 6. Verification and Documentation

- [x] 6.1 Run focused and full Python tests with `conda run -n agent` and fix regressions without using another Python environment.
- [x] 6.2 Run the frontend TypeScript build, browser smoke checks, and launcher smoke checks using the documented npm commands.
- [x] 6.3 Run strict OpenSpec validation for the change and all main specs, then run `git diff --check`.
- [x] 6.4 Update the relevant frontend/Gateway usage notes with the new history and Markdown behavior while keeping mock and Gateway startup instructions distinct.
