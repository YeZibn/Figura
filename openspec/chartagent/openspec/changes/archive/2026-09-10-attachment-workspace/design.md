## Context

See proposal.md for motivation. The desktop client currently has a mock attachment card and a non-functional add button. `AttachmentRegistry` already creates session-scoped opaque IDs, stores safe metadata, validates source hashes, and exposes `load_image`; the Python Gateway currently supports only text messages and deliberately excludes attachment bytes and runtime events from its protocol. The browser client must work without relying on a Tauri-only native file-dialog command.

## Goals / Non-Goals

**Goals:**

- Support image selection, local preview, bounded upload, session-scoped registration, metadata listing, and attachment-aware text submission.
- Reuse the existing `AttachmentRegistry` and `load_image` authorization rather than duplicating filesystem validation in the Gateway.
- Keep image bytes out of SQLite memory records, JSON transcript responses, and the initial model message.
- Make the same React workflow usable in Vite browser development and inside the Tauri WebView.
- Keep mock mode functional with deterministic local attachment data.

**Non-Goals:**

- Streaming upload progress, Agent token streaming, tool-call events, generated visual observations, or cancellation; those belong to the runtime-events change.
- Durable storage of browser-uploaded bytes across Gateway restarts.
- Remote upload, authentication, multi-user sharing, arbitrary filesystem browsing, or unrestricted path-based API input.
- Automatic image understanding, OCR, measurement, or forced `load_image` calls.
- Tauri sidecar lifecycle, packaging, signing, or native file-dialog integration.

## Decisions

### 1. Use the browser File API as the common picker

The React client uses an `<input type="file" accept="image/*">` flow so browser development and the Tauri WebView share the same interaction. `URL.createObjectURL` provides an immediate preview and is revoked when a pending or replaced file is released. A native Tauri dialog is deferred because it would create a second picker path and is not required for the first working upload flow.

Client checks improve feedback but are never authoritative; the Gateway repeats every media type and size validation.

### 2. Upload raw bounded bytes with metadata headers instead of base64 JSON

The client sends one image as an `application/octet-stream` body to a session-scoped upload route and carries the original filename in a validated query/header field. This avoids base64 expansion and avoids adding a multipart parser dependency to the standard-library HTTP server. The server writes the bytes to a process-owned temporary attachment directory with an internal random filename, then registers that file through `AttachmentRegistry`.

The upload response contains only safe metadata. The image body is never echoed to the browser response, SQLite payload JSON, or the model. A later process restart may leave the metadata reference pointing to an unavailable source; the UI must represent that state and allow re-upload.

### 3. Extend the existing Gateway contract with session attachment routes

Add `POST /api/v1/sessions/{id}/attachments` for one bounded binary upload, `GET /api/v1/sessions/{id}/attachments` for safe metadata, and extend `POST /api/v1/sessions/{id}/messages` with an optional `attachmentIds` array. The service resolves every ID against the target session before constructing the Agent turn. Unknown or cross-session IDs fail the whole message before the model is called.

The message builder uses the existing registered-attachment description format. This lets the Agent decide whether to call `load_image` and keeps the existing free-planning behavior intact. The Gateway does not create a multimodal data URL itself.

### 4. Keep preview state separate from model-load state

Frontend attachment records distinguish a locally available preview from the backend registration state and future observation state. A local preview means only that the browser can display the selected file; it does not imply that the Agent has loaded it. The UI retains object URLs only for pending/currently displayed files and never serializes them into Gateway requests or session memory.

### 5. Make temporary file ownership explicit

Uploaded files live below a Gateway-managed temporary root, partitioned by opaque session ID and named with generated IDs rather than user filenames. The Gateway cleans temporary roots on startup and refuses paths supplied by clients. `AttachmentRegistry.validate` remains the final check for existence, media type, size, readability, and content hash before model loading.

### 6. Preserve mock and Gateway adapters behind the same client boundary

Extend `ChartAgentClient` with attachment list/upload and attachment-aware message operations, then implement both mock and Gateway adapters. The workspace chooses the adapter through the existing explicit mode setting. Gateway failures are shown in Chinese and never cause the client to display mock attachments as if they came from the real session.

## Risks / Trade-offs

- [Temporary uploaded bytes disappear after Gateway restart] → Show an unavailable state with a re-upload action; defer durable local attachment storage to a separately scoped change.
- [A raw upload still consumes local disk during the Gateway process] → Enforce a per-file and aggregate limit, use generated paths, and clean the managed root on startup and failed registration.
- [Browser preview and Agent observation can be confused] → Use separate status fields and labels; only `load_image` changes model-load state.
- [The standard-library server gains binary request handling] → Keep upload parsing in a dedicated bounded helper and test content length, media type, filename, and cleanup independently.
- [Changing the frontend client interface can affect mock code] → Extend the interface with focused methods and update mock behavior first, keeping existing text/session methods compatible.

## Migration Plan

1. Add bounded attachment protocol types and Gateway temporary-store helpers.
2. Add session-scoped upload/list routes and attachment-aware Agent message construction.
3. Extend the React client, mock adapter, picker, preview state, and message composer.
4. Add Python API tests, frontend smoke checks, and browser verification for upload, session switching, re-upload, and on-demand loading semantics.
5. Keep existing sessions and CLI attachment flows compatible; old uploaded references remain safe metadata and may be unavailable after Gateway restart.

Rollback is disabling attachment controls or Gateway attachment routes; text-only Gateway sessions, existing CLI attachment behavior, and current `load_image` validation remain usable.
