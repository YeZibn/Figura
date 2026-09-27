## Context

See [proposal.md](proposal.md) for motivation and scope. The Figura store has durable Session, Run, attachment, checkpoint, provider-attempt, tool-fact, continuation, and lifecycle-event records. `FiguraRunStore` currently exposes create and Run-state reads but no Session collection/detail query. `AgentExecutor.execute()` runs synchronously until terminal or an unresolved checkpoint. The React app has mock and ChartAgent clients, a centralized Run lifecycle controller, and shared Session/Conversation/Attachment components; ChartAgent evaluation and preview are part of that existing client contract.

The Figura model allowlist is fixed to Qwen `qwen3.8-flash`, DeepSeek `deepseek-flash`, and MiMo `mimo-v2.6-flash`. Provider availability is locally computable from `ProviderSettings`; health must not make a live request. `SessionMemoryProjector` owns complete provider history; public web projection must not duplicate or mutate it.

## Goals / Non-Goals

**Goals:**

- Provide one local browser path from Session creation through image upload, Provider selection, durable Run execution, and answer display.
- Keep persistence ownership in Figura runtime and expose only a bounded HTTP read/write contract.
- Reuse existing shared React components and run cursor/reconnect behavior without changing ChartAgent contracts.
- Make restart and uncertain-effect behavior visible while preserving the existing fail-closed recovery rules.

**Non-Goals:**

- Tauri shell wiring or packaging.
- Remote/public website hosting, multi-user authentication, or remote file storage.
- Changes to ReAct, Provider protocol, tool behavior, Session-memory completeness, or durable record schema.
- Figura evaluation workspace, generated-chart preview/publication, Session deletion, interruption, retry, or resume UI/API.
- Streaming model tokens or displaying private tool arguments/results as conversation content.

## Decisions

### 1. Add an independent Figura Gateway composition root

Create `src/figura/gateway/` with a service composition root that owns one `FiguraRunStore`, `FiguraAttachmentService`, Provider factory/settings, tool registry/runtime, `RunCoordinator`, `AgentExecutor`, and Run dispatcher. The server binds to `127.0.0.1`; its exact allowed web Origins come from configuration. ChartAgent's Gateway and its store remain untouched.

Use Python's standard-library threaded HTTP server for the small local JSON, raw-image, and SSE surface. This adds no HTTP dependency to `pyproject.toml`; it also keeps the Figura API isolated from legacy `src/chartagent/gateway/`. HTTP handlers validate/decode transport values, call Figura-owned services, map bounded errors, and never contain Agent or persistence rules.

### 2. Add query methods at the existing persistence ownership boundary

Add Session list/get and ordered Run reads through the SessionRepository/RunRepository → `FiguraRunStore` façade → `RunCoordinator` read surface. Run reads use one SQLite snapshot per Session detail. Add an ordered query for persisted `running` Runs for Gateway startup recovery. Keep the existing records and SQLite schema; these operations do not add or update message rows.

Build `web_projection.py` from validated `Session`, `RunState`, attachment metadata, and committed input/final-answer facts. The provider memory projector remains the only source for model history. The web projection exposes the Session's original input and accepted final answer per Run; it does not expose intermediate model responses, tool calls/results, continuation, image bytes, or paths.

### 3. Define the public DTO and field ownership

All routes use `/api/v1`. JSON uses camelCase at the HTTP boundary; adapters map it to frontend domain types. No DTO field below creates a new persisted field.

| Projection | Public fields | Source / ownership |
|---|---|---|
| Provider health | `providerId`, `modelId`, `available`, `reasonCode` | `ProviderFactory.availability()` and fixed `MODEL_IDS`; no network probe |
| Session summary | `id`, `name`, `createdAt`, `updatedAt`, `runCount` | Existing Session name/timestamps plus Run and attachment counts; `updatedAt` is a read-time maximum of the Session timestamp and latest Run/attachment creation time |
| Conversation message | `id`, `runId`, `kind`, `text`, `timestamp`, optional `attachmentIds` | Derived from Run ID + role and the immutable input/final-answer record; IDs are deterministic projection keys, not database IDs |
| Attachment | `id`, `filename`, `mediaType`, `byteCount`, `createdAt` | Existing Session-owned AttachmentMetadata; content is a separate authorized route |
| Run summary | `runId`, `sessionId`, `ordinal`, `status`, `provider`, `model`, `createdAt`, `startedAt`, `finishedAt`, `terminalCode`, `terminalMessage`, `executionState` | Existing Run/checkpoint facts plus dispatcher state; `executionState` is derived as `active` or `needs_reconciliation`, never persisted |
| Lifecycle event | `runId`, `sequence`, `kind`, `timestamp`, allowlisted `payload` | Existing immutable RunStreamEvent; event identity is `runId:sequence` |

`GET /health` returns `{version, status, service, providers}`. `GET /sessions` returns `{sessions}`; `POST /sessions` accepts `{name?}` and returns `{session}`. `GET /sessions/{sessionId}` returns `{session, messages, attachments, runs}`. A message uses `kind: user|assistant`; it is created for every Run input and only for a committed accepted final answer. Failed Runs expose their safe terminal message on the Run summary instead of presenting a failed/intermediate model response as an answer.

`POST /sessions/{sessionId}/attachments?filename=...` accepts raw image bytes. The declared content type is advisory only; the existing attachment service verifies the bytes. `GET /sessions/{sessionId}/attachments` lists metadata, `GET /sessions/{sessionId}/attachments/{attachmentId}/content` returns verified bytes, and `DELETE /sessions/{sessionId}/attachments/{attachmentId}` delegates to existing reference checks.

`POST /sessions/{sessionId}/runs` accepts `{text, attachmentIds, providerId}` and requires an `Idempotency-Key` header. The client does not send `modelId`; the Gateway resolves it from `MODEL_IDS`. The accepted response is `202` with `{run}`. `GET /sessions/{sessionId}/runs/{runId}/history?afterSequence=N` returns the Run summary and durable events after the cursor. `GET /sessions/{sessionId}/runs/{runId}/events?afterSequence=N` streams those events and follows new ones. Event payloads remain lifecycle-only.

Errors use `{error: {code, message}}`. Map invalid input to 400, ownership/not-found to 404, idempotency/active-Run conflicts to 409, unavailable Provider configuration to 503, and storage/integrity failures to a generic 500. Never serialize a Python exception, traceback, provider response body, or request payload.

### 4. Persist first, then dispatch through a bounded worker

The POST handler asks `RunCoordinator.create_run()` to validate and atomically commit the Run before calling `RunDispatcher.ensure_scheduled(run_id)`. It responds without waiting for the model. The dispatcher maintains a process-local scheduled/in-flight set and a bounded worker pool; a duplicate idempotent HTTP request returns the existing Run and calls `ensure_scheduled` so a crash between persistence and scheduling can be repaired safely.

At Gateway startup, list every persisted `running` Run and call the same idempotent scheduler. `AgentExecutor` remains the owner of checkpoint recovery. It may continue a safe pending action; an orphaned started Provider attempt follows the existing unknown-outcome failure rule; a tool-attempt checkpoint remains unresolved and is not replayed. If execution returns `running` at an unresolved tool-attempt checkpoint, the projection derives `executionState: needs_reconciliation`. The UI displays that state without offering replay. Worker completion/failure is reflected by durable Run reads and lifecycle events.

The Gateway emits no synthetic progress events. The persisted `run_created`, `run_completed`, `run_failed`, and `run_interrupted` events remain the event source. SSE first replays events after the requested sequence, then polls/reads for newly committed events until a terminal event; the client controller performs cursor catch-up and reconnect.

### 5. Keep the React Figura contract narrow and separate

Add `FiguraClient` and Figura-only transport/domain types rather than expanding the `ChartAgentClient` contract with fake evaluations, previews, or recovery methods. A thin Figura workspace adapter supplies supported session, attachment, health, run-history, and subscription actions to shared presentation components. Keep provider IDs in a Figura-specific type (`qwen | deepseek | mimo`) so ChartAgent's current Provider union and `types/protocol.ts` remain compatible.

`App.tsx` selects Figura from `VITE_FIGURA_MODE`; `dev:figura` sets it and `VITE_FIGURA_GATEWAY_URL`. The Figura branch hides Session deletion, evaluation, preview, interruption, retry, and resume controls. It reuses the centralized run controller for event sequencing, reconnect, and terminal convergence. Provider availability is read from health; the browser sends only `providerId`.

### 6. Run a local web stack with isolated ports and data

Add `npm run dev:figura` in `frontend/package.json`, implemented by `frontend/scripts/dev-figura.mjs` following the existing launcher ownership model. Defaults: Figura Gateway `127.0.0.1:8766`, Vite `127.0.0.1:1421`; both are distinct from ChartAgent's `8765`/`1420`. Make Vite's port configurable through `VITE_DEV_PORT` while preserving its existing default. Start the Gateway using `conda run -n agent python -m figura.gateway`, wait for health, then start Vite. The launcher owns both child process groups and stops both on startup error, SIGINT, or SIGTERM.

The Python entry point loads the project-root `.env` with `python-dotenv` and `override=False`, so inherited process values win. It reads `FIGURA_DATA_DIR`, defaulting to `<project-root>/.figura`, and accepts only the configured Vite Origin. The `.figura/` directory is added to `.gitignore`. Vite receives the Figura mode, Gateway URL, and local port only; Provider secrets never use a `VITE_` variable.

## Risks / Trade-offs

- **A local Gateway accepts requests from a browser process with local reachability** → bind loopback, allow exact local Origins, validate Origin on state-changing routes, scope every lookup by Session, and return no local paths or credentials.
- **The browser can lose the POST response after the Run was durably created** → require idempotency keys and schedule the original Run again only through the same dispatcher deduplication path.
- **Gateway restart occurs during an external effect** → use the existing Agent checkpoint recovery rules; do not infer that an uncertain Provider request or tool effect did not happen.
- **An unresolved tool attempt has no web reconciliation control in this change** → expose `needs_reconciliation` in the safe Run projection and keep the Session blocked from starting a second Run until a later, separately specified recovery surface exists.
- **Full Session history can grow beyond Provider limits** → preserve existing Session-memory behavior; request construction fails before Provider dispatch when hard limits are exceeded, and the UI does not imply that history was shortened.
- **Existing UI components assume ChartAgent-only actions** → use a Figura-specific workspace adapter and conditional capabilities rather than fabricating unsupported calls or weakening `ChartAgentClient` types.

## Migration Plan

1. Add query-only Store/Coordinator methods and the read-time web projection; no existing database migration is required.
2. Add the Figura Gateway API, dispatcher, startup recovery, and loopback development entry point.
3. Add the Figura web client/mode and connect supported shared UI actions.
4. Add the local launcher, isolated ports/data directory, `.gitignore` entry, and development usage documentation.
5. Run the planned Figura API/UI/launcher acceptance scenarios. Rollback consists of removing the new Gateway/client/launcher entry points; existing Figura SQLite records remain readable by the existing runtime.

## Open Questions

None. The first delivery is scoped to the local browser development workflow; remote deployment has a different trust and storage boundary and is outside these specs.
