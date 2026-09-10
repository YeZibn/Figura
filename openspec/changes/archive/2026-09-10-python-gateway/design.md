## Context

See proposal.md for motivation. The React desktop client currently calls a typed `ChartAgentClient` mock adapter. The Python CLI creates `Agent` instances with `SQLiteAgentMemory` for opt-in named sessions, but there is no browser-compatible API for the same session lifecycle. The existing session store is keyed by human-readable name while the frontend client model uses opaque session IDs, and the existing trace stream is intentionally diagnostic rather than a frontend transport.

## Goals / Non-Goals

**Goals:**

- Introduce a local HTTP/JSON service boundary that can run from the existing `agent` Conda environment.
- Map persistent sessions and completed runs into a stable client protocol without exposing storage or provider types.
- Make the existing frontend client interface usable against the real Agent while retaining deterministic mock mode.
- Keep HTTP request parsing, error mapping, Agent construction, and transcript projection separately testable.

**Non-Goals:**

- Streaming tokens, trace events, tool-call progress, visual observations, or cancellation.
- Receiving files from the browser, registering attachments, or returning preview bytes and URLs.
- Binding beyond loopback, authentication, multi-user access, remote hosting, or CORS policies broader than local development.
- Tauri commands, Tauri-managed process lifecycle, bundled Python runtimes, or distributable sidecars.

## Decisions

### 1. Use a loopback HTTP/JSON boundary with the Python standard library

Implement a small HTTP server using the standard library and bind it to `127.0.0.1` by default. It exposes health, named-session collection, named-session detail, and message-submission routes. JSON is the only supported request and response format. The server is intentionally thin: a gateway service converts HTTP input to domain calls and a separate projector converts results to protocol objects.

The standard library is selected over FastAPI or Flask because the current runtime has no web-framework dependency and the initial route surface is small. It avoids dependency and packaging expansion before the protocol proves itself. A framework can later replace the transport without changing the service or response contract.

### 2. Use opaque gateway session IDs while keeping existing session names as display values

The gateway lists and returns the durable `Session.id`; requests resolve that ID to a session name internally before constructing `SQLiteAgentMemory`. New session creation accepts a display name and returns the generated ID. This avoids using a mutable user-facing name as a URL key and aligns the gateway with the frontend protocol.

The existing SQLite interface is name-oriented, so the gateway needs a small read-only lookup/query layer scoped to the same database. It must not pass database rows or SQL errors through HTTP.

### 3. Project completed records into a deliberately narrow transcript

For the initial protocol, session detail and successful message responses contain ordered user and final assistant text from completed runs. They do not reconstruct tool calls, tool results, visual observations, or attachment cards. Failed and interrupted runs remain excluded, matching memory-context semantics.

This narrow projection is selected over forwarding trace events because the current frontend client can render basic conversation immediately, whereas exposing in-flight event ordering, replay, images, and cancellation is a separate contract. That work belongs to `agent-runtime-events` after the Gateway's lifecycle and error model are established.

### 4. Reuse the CLI's Agent assembly through a shared factory

Move the common setup of environment loading, `LLMClient`, tool registry, built-ins, chart tools, attachment registry, and named memory into a reusable factory/service invoked by both the CLI and gateway. The gateway text endpoint does not accept attachment references in this change, but construction retains the existing safe attachment capability for future integration.

Duplicating setup in the gateway would make tool availability and system guidance diverge from the CLI. Turning the gateway into a subprocess wrapper around the interactive CLI is rejected because prompt and terminal rendering are not a stable application protocol.

### 5. Explicit frontend mode chooses mock or gateway adapter

Add a `gatewayClient` implementing the present `ChartAgentClient` interface. A Vite environment value selects `mock` by default or `gateway` when requested; the base URL also has a local development default. The app does not silently fall back to mock data when an explicit gateway request fails, because that would present stale fake data as real session state.

### 6. Apply local input, output, and error boundaries

The server limits request body size, requires JSON content for body routes, validates bounded session names and message text before Agent execution, and sends only mapped error codes and bounded display-safe messages. It never returns tracebacks, environment values, credentials, raw provider responses, attachment paths, or binary content. A narrow development CORS allowlist permits the Vite origin; native Tauri requests use the same loopback endpoint without expanding the bind address.

## Risks / Trade-offs

- [A synchronous model call can hold an HTTP connection for a long time] → Use clear client loading states and request timeouts; add asynchronous runs or event streaming only in the dedicated runtime-events change.
- [The existing SQLite API lacks lookup-by-ID and transcript-read methods] → Add bounded gateway-facing repository methods with focused persistence tests instead of giving the HTTP layer raw database access.
- [The Agent needs provider configuration while mock mode does not] → Keep gateway health independent of model initialization; report setup errors only when a run is requested.
- [A local HTTP port can conflict with another process] → Make host and port configurable with safe loopback defaults and return a clear startup error.
- [Standard-library routing grows awkwardly] → Keep the handler minimal and isolate route dispatch, schemas, service, and projection so a later transport replacement is low-risk.
- [Browser development needs cross-origin access] → Restrict CORS to configured local development origins and never use wildcard origins or a non-loopback bind by default.

## Migration Plan

1. Add typed gateway protocol objects, session repository projection, Agent service factory, and loopback server entry point.
2. Add API tests with fake Agent/client dependencies, including protocol, validation, not-found, conflict, and sanitized-error paths.
3. Add the frontend gateway adapter, explicit mode configuration, and adapter tests while leaving mock mode as the default.
4. Run browser development against the loopback server and document both processes using the `agent` Conda environment for Python commands.
5. In later changes, add attachment upload, runtime event streaming, and Tauri process management without changing the established session/message routes.

Rollback is disabling gateway mode or removing the new gateway module and frontend adapter; the existing CLI, mock desktop client, and persisted named sessions remain intact.
