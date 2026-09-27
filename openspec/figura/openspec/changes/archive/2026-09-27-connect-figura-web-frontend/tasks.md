## 1. Session and Run read projections

- [x] 1.1 Add Session list/get queries and ordered Run queries at the SessionRepository/RunRepository boundary, exposed through `FiguraRunStore` and `RunCoordinator`.
- [x] 1.2 Add a consistent Session snapshot read that includes its Session, Run states, event cursors, and retained attachment metadata without writing history rows.
- [x] 1.3 Add the safe web projection for Session summaries, user/final-answer messages, attachment metadata, Run summaries, and derived `executionState`.
- [x] 1.4 Add an ordered query for persisted running Runs to support Gateway startup recovery.

## 2. Figura Gateway composition and local HTTP boundary

- [x] 2.1 Create `src/figura/gateway/` with an application composition root for Store, AttachmentService, ProviderFactory, ToolRegistry/Runtime, RunCoordinator, AgentExecutor, and dispatcher.
- [x] 2.2 Add the local HTTP server entry point, JSON parsing/serialization, route dispatch, bounded request handling, safe error mapping, and exact-Origin validation.
- [x] 2.3 Add `/api/v1/health` with fixed Provider/model IDs and configuration-only availability reporting; verify the health path does not call Providers.
- [x] 2.4 Bind the server to loopback and ensure public responses and errors omit credentials, raw endpoints, environment values, payloads, continuations, tool facts, and local paths.

## 3. Session and image attachment API

- [x] 3.1 Add Session list/create/detail routes using the web projection and stable ordinal ordering.
- [x] 3.2 Add Session-scoped attachment list, raw image upload, content read, and delete routes backed by `FiguraAttachmentService`.
- [x] 3.3 Map ownership, validation, size, and referenced-attachment failures to bounded API errors without leaking whether cross-Session resources exist.

## 4. Asynchronous Run execution and event transport

- [x] 4.1 Add Run creation request mapping for `text`, ordered `attachmentIds`, and `providerId`; resolve `modelId` on the server and require the `Idempotency-Key` header.
- [x] 4.2 Add a bounded Run dispatcher with in-process scheduling deduplication; persist through `RunCoordinator` before scheduling and return the existing Run on idempotent replay.
- [x] 4.3 Recover persisted running Runs at Gateway startup by scheduling each through `AgentExecutor` and preserving current Provider/tool uncertainty rules.
- [x] 4.4 Add Run history reads and replayable SSE from a requested event sequence using persisted lifecycle events and the `runId:sequence` event identity.
- [x] 4.5 Derive `executionState: needs_reconciliation` for an unresolved tool-attempt checkpoint without replaying the tool or mutating durable Run state.

## 5. Figura React client and workspace mode

- [x] 5.1 Add Figura-only transport/domain types, HTTP adapter, DTO mappers, attachment content URLs, history reads, and SSE subscription support.
- [x] 5.2 Add a narrow Figura workspace adapter and `VITE_FIGURA_MODE` selection while retaining `ChartAgentClient`, `gatewayClient.ts`, and mock/ChartAgent mode behavior.
- [x] 5.3 Connect shared Session, Conversation, and Attachment components to Figura projections; render complete Run-ordered user/final-answer messages and safe terminal/reconciliation states.
- [x] 5.4 Add Qwen, DeepSeek, and MiMo selection with configuration availability; send only Provider IDs from the browser.
- [x] 5.5 Connect Run submission, per-submit idempotency keys, active-Run gating, event-cursor reconnect, reload recovery, and Session refresh on terminal events through the centralized run controller.
- [x] 5.6 Hide unsupported Figura actions for Session deletion, evaluations, generated-chart preview, interruption, retry, and resume while preserving their ChartAgent presentation.

## 6. Local web development workflow

- [x] 6.1 Add `npm run dev:figura` and a launcher that starts the `agent` Conda Gateway and Vite on loopback, waits for health, and cleans up both owned process groups on failure, SIGINT, and SIGTERM.
- [x] 6.2 Add isolated defaults for Figura ports `8766`/`1421`, make Vite's existing port configurable without changing its `1420` default, and pass Figura mode/Gateway URL without exposing secrets to Vite.
- [x] 6.3 Load project `.env` in the Python entry point with inherited environment values taking precedence; use `FIGURA_DATA_DIR` with `.figura/` as the default.
- [x] 6.4 Add `.figura/` to `.gitignore` and document the local Figura web startup command and required Provider configuration.

## 7. Contract and integration verification

- [x] 7.1 Add Python coverage for safe projections, Session ownership, attachment validation/deletion, Provider availability, idempotent Run creation, async dispatch, startup recovery, SSE replay, and error redaction.
- [x] 7.2 Add frontend smoke coverage for Figura mode selection, three Providers, session history/attachments, Run terminal convergence, reconciliation display, and unchanged ChartAgent/mock modes.
- [x] 7.3 Add launcher lifecycle coverage for readiness, startup failure, SIGINT/SIGTERM cleanup, and port ownership.
- [x] 7.4 Run the focused Figura/frontend checks, `frontend npm run build`, applicable smoke commands, `git diff --check`, and strict OpenSpec change validation.
