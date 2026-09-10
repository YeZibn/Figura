## 1. Gateway run protocol and in-memory runtime

- [x] 1.1 Define bounded run request, run status, event envelope, terminal result, and observation-reference protocol types with stable JSON serialization.
- [x] 1.2 Implement a bounded in-memory run manager with opaque run IDs, session ownership, monotonic event sequences, terminal states, replay buffers, and retention cleanup.
- [x] 1.3 Adapt the existing sanitized Agent trace boundary into run events for model turns, tool calls, tool results, reasoning availability, final answers, budget termination, and failures without changing model history.
- [x] 1.4 Implement the run-scoped visual observation store with media/size/count limits, opaque IDs, session ownership, TTL cleanup, and shutdown cleanup.

## 2. Gateway asynchronous execution and transport

- [x] 2.1 Add an asynchronous run submission operation that validates the session, text, and attachment IDs before returning an initial run ID and running state.
- [x] 2.2 Route synchronous message execution through the same run manager and preserve its existing completed-transcript response for compatibility.
- [x] 2.3 Add the loopback SSE event endpoint with ordered frames, bounded heartbeats, terminal close behavior, and `Last-Event-ID` replay.
- [x] 2.4 Add the scoped temporary observation endpoint and enforce run/session ownership, media limits, expiration, and bounded errors.
- [x] 2.5 Preserve Gateway mode's no-fallback behavior and ensure active run failures do not corrupt prior completed session history.
- [x] 2.6 Add Gateway tests for asynchronous acceptance, event ordering, terminal states, reconnect replay, payload truncation, sync compatibility, observation access, and session isolation.

## 3. Tauri Gateway supervisor

- [x] 3.1 Implement an owned Gateway supervisor in `src-tauri` that launches an executable plus argument list without a shell and tracks the child handle separately from externally managed services.
- [x] 3.2 Add configurable Gateway host/port, launcher executable, launcher arguments, and bounded startup/shutdown timeouts with the documented Conda `agent` development default.
- [x] 3.3 Add Tauri commands or events for Gateway starting, ready, unavailable, and stopped states, including compatible health/version verification.
- [x] 3.4 Register application shutdown cleanup so only a Gateway child owned by the current Tauri instance is gracefully stopped.
- [x] 3.5 Add Rust checks or focused runtime tests for startup failure, health timeout, external Gateway preservation, and owned-child cleanup.

## 4. React live-run client and workspace

- [x] 4.1 Extend the frontend protocol and `ChartAgentClient` boundary with run start, event subscription, event mapping, run states, and temporary observation references.
- [x] 4.2 Implement Gateway SSE consumption with sequence tracking, reconnect handling, terminal detection, and bounded client-side error mapping.
- [x] 4.3 Implement a mock live-run adapter that emits the same typed event sequence without network access and without changing explicit Gateway-mode behavior.
- [x] 4.4 Update the workspace state reducer to render connecting/running/completed/failed/unavailable states and append chronological tool execution details without duplicate transcript entries.
- [x] 4.5 Render visual observations from temporary observation references with loading, available, expired, and unauthorized states distinct from local attachment previews.
- [x] 4.6 Preserve Simplified Chinese UI, session switching cleanup, attachment selection behavior, collapsed execution details, and prior completed conversation content during failures.
- [x] 4.7 Add frontend smoke coverage for mock events, Gateway event mapping, reconnect/terminal handling, observation rendering, no-fallback behavior, and duplicate-free transcript refresh.

## 5. Verification and documentation

- [x] 5.1 Document Gateway run/event endpoints, runtime launcher configuration, Conda `agent` development startup, observation retention, and mock versus Gateway behavior.
- [x] 5.2 Run focused Gateway and Agent tests with `conda run -n agent`, then run the full Python regression suite.
- [x] 5.3 Run frontend smoke and production build checks, plus Tauri Rust checks where the local toolchain is available. Frontend checks passed; no Rust toolchain is installed locally.
- [ ] 5.4 Manually verify a local Tauri/Gateway flow for startup readiness, real tool events, visual observation display, terminal transcript refresh, Gateway failure, and shutdown cleanup.

> 5.4 browser/Gateway equivalent flow passed for startup health, SSE tool events, temporary visual observations, terminal transcript refresh, and no-fallback failure handling. Tauri startup/shutdown cleanup remains pending until a Rust toolchain is available.

## 6. Unified development startup

- [x] 6.1 Add a supervised `npm run dev:gateway` launcher that starts the Gateway with `conda run -n agent`, waits for health readiness, and starts Vite with explicit Gateway mode.
- [x] 6.2 Forward launcher termination signals and clean up only the Gateway and frontend processes created by the launcher.
- [x] 6.3 Add a `tauri:dev:gateway` script alias that enables Gateway mode while preserving Tauri supervisor ownership of the Gateway child.
- [x] 6.4 Add launcher lifecycle tests and update README plus the frontend smoke checklist with the single-command workflows and failure behavior.
