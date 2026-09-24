## 1. Persistent Attachment Storage

- [x] 1.1 Refactor Gateway attachment storage to resolve a persistent application-data root while preserving `CHARTAGENT_ATTACHMENT_DIR` and test injection overrides.
- [x] 1.2 Remove startup directory wiping and implement bounded atomic file writes with user-only directory/file permissions and idempotent cleanup helpers.
- [x] 1.3 Add safe legacy-source migration for still-readable attachment paths and preserve unavailable metadata when the old source is already gone.
- [x] 1.4 Add tests for restart persistence, root resolution, upload rollback, permissions where supported, hash changes, missing files, and orphan cleanup behavior.

## 2. SQLite and Gateway Lifecycle

- [x] 2.1 Add ID-based SQLite session deletion and attachment deletion primitives that return enough metadata for managed file cleanup while retaining CLI name-based compatibility.
- [x] 2.2 Add RunManager/session lifecycle coordination so active runs are detected atomically enough to reject session deletion with `session_busy`.
- [x] 2.3 Implement Gateway service methods for deleting idle sessions and attachments, including managed-root path checks and bounded storage errors.
- [x] 2.4 Implement attachment content reads that reuse ownership, media-type, size, readability, and hash validation without exposing canonical paths.
- [x] 2.5 Add service tests for session cascade deletion, attachment file cleanup, cross-session isolation, active-run protection, content validation, and failed cleanup recovery.

## 3. HTTP Protocol

- [x] 3.1 Add `DELETE /api/v1/sessions/{session_id}` with versioned success and structured conflict/not-found errors.
- [x] 3.2 Add `DELETE /api/v1/sessions/{session_id}/attachments/{attachment_id}` with session-scoped authorization and bounded responses.
- [x] 3.3 Add `GET /api/v1/sessions/{session_id}/attachments/{attachment_id}/content` with correct media type, bounded binary response, CORS behavior, and safe fault handling.
- [x] 3.4 Extend HTTP route tests for method dispatch, binary previews, malformed IDs, cross-session access, unavailable sources, and sensitive-data redaction.

## 4. Frontend Client Boundary

- [x] 4.1 Extend the shared `ChartAgentClient` contract with session deletion, attachment deletion, and attachment content URL operations.
- [x] 4.2 Implement the new operations in the Gateway client with stable error mapping and accurate preview URLs from Gateway metadata.
- [x] 4.3 Update the mock client to support equivalent deletion, attachment removal, and preview behavior without network access.
- [x] 4.4 Update protocol types and Chinese user-facing error messages for busy sessions, deletion failures, unavailable previews, and persistence states.

## 5. React Workspace UX

- [x] 5.1 Enable the session operations menu and add an accessible Chinese delete confirmation dialog that does not delete optimistically.
- [x] 5.2 Implement deterministic active-session recovery after deletion, including cleanup of subscriptions, pending files, selected attachment IDs, live events, and empty-state handling.
- [x] 5.3 Use Gateway-backed preview URLs for persisted attachments while retaining browser object URLs only for pending/current mock previews.
- [x] 5.4 Add registered-attachment remove actions with confirmation, retry/error behavior, and selection cleanup.
- [x] 5.5 Update responsive styles, focus states, labels, and smoke checks for the new session and attachment controls.

## 6. Specs, Documentation, and Verification

- [x] 6.1 Update the main OpenSpec capabilities through the sync workflow after implementation matches the change specs.
- [x] 6.2 Update README and environment documentation to describe persistent attachment storage, deletion semantics, preview routes, and the unavailable-source recovery path.
- [x] 6.3 Run `conda run -n agent python -m pytest -q` and fix Gateway/session/attachment regressions.
- [x] 6.4 Run frontend typecheck/build and the existing frontend smoke and launcher lifecycle checks.
- [x] 6.5 Validate the completed change with OpenSpec and confirm no Tauri/Rust files were required or changed.
