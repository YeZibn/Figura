## Context

The current React client talks to a loopback Gateway over HTTP, while the Tauri shell only exposes a health-independent `ping` command. The Gateway creates an Agent runtime per synchronous message and projects durable memory down to user and assistant text, so existing CLI trace events and generated visual observations are not available to the desktop UI.

The change must preserve mock mode, named-session persistence, attachment authorization, the existing synchronous message contract, and the rule that reasoning, credentials, provider payloads, image bytes, and raw traces are not persisted in session memory. Python commands and tests continue to use the Conda `agent` environment.

## Goals / Non-Goals

**Goals:**

- Give the Tauri shell an explicit, owned Gateway process lifecycle and a readiness state.
- Add an asynchronous run path while keeping the existing synchronous message path compatible.
- Forward bounded, ordered Agent trace events to the desktop client.
- Make generated visual observations available through short-lived, run-scoped resources without placing bytes in event JSON or SQLite.
- Let mock and Gateway adapters drive the same live-run UI contract.

**Non-Goals:**

- Changing the Agent's model-message ordering, context policy, or provider reasoning behavior.
- Persisting raw execution traces, active run state, or generated observation bytes across Gateway restarts.
- Implementing remote access, authentication, multi-user concurrency, or a general job queue.
- Adding run cancellation in this change; cancellation can build on the run registry after the event contract is stable.
- Bundling a new Python distribution into release artifacts; this change defines an executable/argument launcher boundary and keeps the documented Conda development path.

## Decisions

### 1. Use a Tauri-owned supervisor with an explicit launcher configuration

Rust will keep the child process handle, an `owned` flag, the Gateway base URL, and bounded startup/shutdown deadlines. Startup will launch an executable plus argument list rather than a shell command, poll `/api/v1/health` until the expected protocol version is available, and expose status to React through Tauri commands or events. Shutdown will only terminate the child recorded by that supervisor.

Development defaults will resolve to the project Gateway through the `agent` Conda environment, while executable and arguments remain configurable for packaged or externally managed deployments. Mock mode will never call the supervisor. This avoids hard-coding a user-specific Conda path and avoids silently attaching shutdown behavior to an unrelated process.

An alternative was to let React spawn or discover a fixed port. That cannot own process cleanup reliably and leaves the Tauri app unable to distinguish a compatible Gateway from an unrelated local service.

### 2. Add an asynchronous run manager beside the existing synchronous service path

The Gateway service will own a bounded in-memory registry of active and recently terminal runs. Each accepted run receives an opaque run ID, a session owner, a monotonic event sequence, a bounded replay buffer, a terminal state, and a short-lived observation store. A worker executes the existing Agent runtime using a dedicated SQLite connection and emits through the existing sanitized trace boundary.

The synchronous message route will submit through the same run manager and wait for its terminal result, preserving current callers. The new run route returns immediately; the SSE route consumes the run's replay buffer and waits for later events. Completed user/final records continue to be written by the existing memory layer, while event buffers and observations disappear with their retention window or Gateway process.

### 3. Use SSE for local event delivery

Server-sent events fit the one-way Gateway-to-client flow, work over the current loopback HTTP server, and let the browser reconnect with `Last-Event-ID`. Each frame will contain a bounded event name, run ID, sequence, timestamp, and JSON payload. The server will send a terminal frame and close, with a bounded heartbeat for an idle run.

WebSocket was considered but would add bidirectional lifecycle complexity before cancellation is in scope. Polling was rejected because it delays tool and visual-observation details and makes ordering/replay less precise.

### 4. Keep visual observation bytes outside event JSON

The Agent execution path will pass generated image evidence to a run-scoped observation store in addition to the existing trace summary. The trace event contains only an opaque observation ID, caption, media type, dimensions, and bounded size metadata. A separate loopback resource validates the run/session ownership and returns the bounded image bytes until the short retention deadline.

This preserves the current trace and memory sanitization boundary while giving the desktop client enough information to render the same visual evidence it can inspect in CLI trace mode.

### 5. Make live execution a client-boundary concern

The React client boundary will expose start-run and event-subscription operations rather than making `App` know whether events came from SSE or a mock generator. The Gateway adapter will map protocol events into typed client events; the mock adapter will emit a deterministic sequence including at least one tool call, result, and terminal answer. The UI will append execution items by event sequence, fetch observation previews by opaque URL, and refresh the durable transcript after the terminal event.

The primary conversation remains readable while execution details are collapsed by default. Gateway errors never trigger a mock fallback; mock mode remains an explicit offline choice.

### 6. Provide one supervised development startup command

Add a frontend development launcher exposed as `npm run dev:gateway`. It will
start `conda run -n agent python -m chartagent.gateway` and the Vite client with
`VITE_CHARTAGENT_MODE=gateway` as child processes, wait for the Gateway health
endpoint before treating the client as ready, forward termination signals, and
clean up only the child processes it created. It will preserve configurable
Gateway host and port values and report a bounded startup error when Conda or
the health check is unavailable.

Add a `tauri:dev:gateway` script alias that sets `CHARTAGENT_MODE=gateway` and
`VITE_CHARTAGENT_MODE=gateway` before invoking the existing Tauri development
command. Tauri remains the owner of the Gateway child in this mode; the
browser launcher is not nested inside Tauri and must not be used to start a
second Gateway for the same port. Plain `npm run dev` remains the explicit
mock/frontend-only workflow.

An alternative was to make plain `npm run dev` always start Python. That would
break offline mock development and would conflict with the Tauri supervisor's
ownership boundary, so the Gateway launcher is a separate explicit command.

## Risks / Trade-offs

- [Risk] A Gateway process can exit while a run is active, leaving the client with no terminal event. → Mark the runtime unavailable, close the stream, preserve prior completed history, and require a bounded reconnect/retry flow; do not fabricate a final answer.
- [Risk] SSE replay buffers can grow with verbose tool output. → Bound event count and serialized payload size, sanitize through the trace boundary, and emit truncation markers.
- [Risk] Generated observations can consume memory. → Enforce per-run image count/byte limits and a short TTL; release resources on terminal cleanup and Gateway shutdown.
- [Risk] A fixed loopback port may already be occupied. → Treat an incompatible health response or bind failure as an explicit unavailable state and support a configured port, without killing the existing process.
- [Risk] The unified launcher can leave one child alive after a terminal or signal failure. → Track only spawned process handles, forward termination signals, and perform bounded group cleanup without terminating unrelated processes.
- [Risk] Packaged environments may not have Conda. → Keep Conda as the development/test default and make the launcher executable/arguments configurable for a future bundled runtime.

## Migration Plan

1. Add the typed Gateway run/event protocol and run manager without changing existing session or attachment records.
2. Add the asynchronous routes and observation resource, then route the existing synchronous operation through the same execution path.
3. Add the Tauri supervisor and readiness reporting, plus the one-command browser and Tauri Gateway-mode launch aliases.
4. Switch Gateway-mode React submission to live events, retain mock mode, and verify transcript projection after terminal events.
5. Run focused Python tests, the full Python suite, launcher lifecycle checks, frontend smoke/build checks, and a local Tauri/Gateway manual flow using `conda run -n agent`.

Rollback is to stop using the new run/event client path and retain the existing synchronous Gateway endpoint. No schema migration is required; stopping the Gateway discards only active run buffers and temporary visual observations.

## Open Questions

None that change the scope or architecture. The packaged Python runtime choice remains a later distribution concern because the launcher boundary supports either a configured executable or a future bundled sidecar.
