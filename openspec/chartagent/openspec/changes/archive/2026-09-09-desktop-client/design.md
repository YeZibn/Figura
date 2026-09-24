## Context

See proposal.md for motivation. The repository currently contains the Python ChartAgent core and CLI but no frontend or Tauri project. The first client milestone must be independently runnable without provider credentials, while leaving later Python gateway, upload, and event-stream changes a stable integration boundary.

## Goals / Non-Goals

**Goals:**

- Establish a Tauri 2 desktop shell with a React, TypeScript, and Vite frontend.
- Represent sessions, conversation items, attachments, and execution details with explicit frontend types.
- Provide a functional mock workspace covering selection, creation, message submission, attachment display, and detail expansion.
- Keep all user-visible labels, prompts, mock content, and interaction feedback in Simplified Chinese; technical names and protocol identifiers may remain in English.
- Keep UI components independent from Python classes, SQLite, and Tauri-specific backend commands.
- Keep the same frontend build usable in a browser during development and inside the Tauri WebView.
- Verify desktop and narrow-window layouts with automated frontend checks or a repeatable visual test.

**Non-Goals:**

- Real Python API routes, SQLite access, file upload, attachment registration, Agent execution, SSE, or provider calls.
- Tauri sidecar packaging, Python runtime bundling, signing, notarization, or cross-platform distribution.
- Authentication, multi-user collaboration, cloud synchronization, or remote deployment.

## Decisions

### 1. Use Tauri 2 with React, TypeScript, and Vite

Tauri provides the desktop window and future native file-dialog integration while React gives the client a mature component model for session, conversation, attachment, and event views. TypeScript makes the future API boundary explicit. Vite keeps the development loop small and also permits browser-only UI testing.

A pure browser page was not selected as the target product form because the workflow is local-first and file-oriented. Electron was not selected because its bundled browser runtime is heavier than needed. PySide was not selected because it would split the frontend model from the web-compatible UI path and make later WebView reuse harder.

### 2. Keep the first milestone mock-first and adapter-driven

Define a client interface for listing/creating/selecting sessions, reading session data, and submitting a message. Implement a deterministic mock adapter with representative records. Components depend on the interface and typed data, not on mock-specific values. A later Python gateway adapter can replace it without changing presentation components.

### 3. Use a three-region workspace with responsive degradation

The desktop layout contains a session sidebar, a primary conversation panel, and an attachment/details panel. On narrow windows, the side regions collapse into accessible sections or stack below the conversation; the composer remains available. Avoid nested card-heavy layout: use full-height panels and small bordered items for repeated messages/attachments.

### 4. Model execution details as first-class UI data

Conversation entries use a discriminated union for user, assistant, tool call, tool result, visual observation, and error items. Tool details are collapsed initially and can expand to show bounded arguments/results. Visual observations use image URLs or mock assets only at the UI layer; this does not imply durable image bytes or model context.

User-facing copy is maintained separately from protocol identifiers. Labels such as session, attachment, tool call, visual observation, loading, empty, and error states are rendered in Simplified Chinese. Names such as load_image, measure_bars, attachment_id, React, Tauri, and Vite remain unchanged where they are technical identifiers or product names.

### 5. Keep Tauri integration thin

The initial Tauri command surface is limited to application startup and static frontend loading. No Python process lifecycle or sidecar behavior is introduced. A future gateway can be reached through a replaceable HTTP client, and a future Tauri adapter can be introduced only where native capabilities are needed.

## Risks / Trade-offs

- [Node/Rust toolchains may be unavailable on a development machine] → Document the required versions and retain a browser/Vite development command for UI work.
- [Mock behavior diverges from the future Python gateway] → Define typed client contracts and keep mock payloads shaped like the planned session/run/attachment protocol.
- [Three panels become cramped in a small Tauri window] → Use responsive CSS with a minimum usable composer and stack/collapse secondary panels below a breakpoint.
- [Frontend dependencies add project complexity] → Keep the initial dependency set limited to React, Vite, TypeScript, Tauri, and test tooling; avoid a component framework until interaction needs justify it.
- [Tauri packaging is mistaken for completion] → Explicitly defer sidecar, signing, and distribution to a later change.

## Migration Plan

1. Add the frontend and Tauri project without changing Python behavior.
2. Run the mock workspace in a browser for rapid UI verification.
3. Run the same built frontend through Tauri development mode.
4. Later replace the mock adapter with the session gateway, attachment upload, and Agent events adapters in their separate changes.

Rollback is removing the desktop client directories and related package scripts; the existing Python CLI and core modules remain unaffected.
