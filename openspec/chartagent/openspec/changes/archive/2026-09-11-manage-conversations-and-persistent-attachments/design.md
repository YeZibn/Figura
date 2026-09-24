## Context

See `proposal.md` for the user-facing motivation. The current Gateway stores uploaded bytes in a process-managed temporary directory, stores their canonical paths in SQLite, and clears the directory during Gateway initialization. The React adapter receives attachment metadata without a preview URL and keeps only a browser object URL for the current page. SQLite already cascades session deletion to runs, records, and attachment metadata, but its public deletion helper is name-based while Gateway routes use opaque session IDs. `RunManager` owns active runs in memory and has no durable cancellation protocol.

The implementation must remain local-only, use the existing Python Gateway and SQLite boundaries, preserve lazy model-side `load_image`, and keep the mock client usable. Python commands and tests use the Conda `agent` environment. Tauri/Rust is outside this change.

## Goals / Non-Goals

**Goals:**

- Make uploaded source images survive frontend and Gateway restarts when the local application data directory is intact.
- Provide safe session-scoped preview/content access without exposing canonical paths or placing image bytes in JSON or memory history.
- Provide consistent Gateway, mock-client, and React operations for deleting sessions and registered attachments.
- Keep deletion atomic at the metadata level, clean managed files, and protect sessions with active runs.
- Preserve compatibility with existing synchronous messages, asynchronous SSE runs, lazy attachment loading, and the current environment variable conventions.

**Non-Goals:**

- Storing image bytes in SQLite, cloud synchronization, multi-user authorization, undo/restore, bulk deletion, or run cancellation UI.
- Persisting generated visual observations or provider traces.
- Recovering an old source whose bytes were already removed before this change; only still-readable legacy files can be migrated.

## Decisions

### 1. Use a persistent attachment directory next to the session database

Resolve the attachment root in this order:

1. An explicit `attachment_root` service argument or `CHARTAGENT_ATTACHMENT_DIR` environment value.
2. The `attachments/` directory beside an explicitly supplied SQLite database.
3. `$CHARTAGENT_DATA_DIR/attachments/`, or `~/.chartagent/attachments/` when the data directory is unset.

The root and per-session directories use user-only permissions where supported. Generated filenames remain opaque and are not based on the user filename. Uploads are validated in memory, written to a unique temporary file within the session directory, flushed and atomically renamed before SQLite metadata is committed. If metadata persistence fails, the staged file is removed. Startup creates the root but never clears it.

This keeps binary I/O out of SQLite and makes the existing path-and-hash attachment registry reusable. SQLite remains the source of ownership and metadata; the file store remains the source of bytes. The existing `CHARTAGENT_ATTACHMENT_DIR` override is preserved for tests and custom deployments.

Alternative: store image BLOBs in SQLite. Rejected because it makes the session database grow with every upload, increases read/write contention, and conflicts with the existing provider-neutral metadata design.

### 2. Keep the attachment ID-to-file mapping in SQLite, but validate the boundary on every read

The attachment row continues to contain the opaque ID, owning session ID, managed canonical path, filename, media type, byte count, hash, and timestamps. The Gateway never serializes the path. Listing metadata runs the existing ownership and integrity checks so `status` and `preview_available` describe the current source.

The content endpoint receives both session ID and attachment ID. It first resolves the session and row, verifies ownership, validates the managed path, and only then reads bounded bytes. The response is binary with the stored/validated media type; errors use the existing JSON fault envelope. The React adapter derives a URL from the endpoint and never reconstructs a local path.

Alternative: return base64 or data URLs in session JSON. Rejected because it inflates every transcript response and would blur the existing boundary between metadata and model-visible image content.

### 3. Add explicit session and attachment lifecycle operations

Expose:

```text
DELETE /api/v1/sessions/{session_id}
DELETE /api/v1/sessions/{session_id}/attachments/{attachment_id}
GET    /api/v1/sessions/{session_id}/attachments/{attachment_id}/content
```

Deletion responses use the versioned JSON envelope and include only opaque IDs and a boolean/result marker. Session deletion resolves by ID, checks `RunManager` for an active run, then deletes durable rows by session ID with foreign keys enabled. The file store removes the session's managed attachment directory after the database operation succeeds. Individual attachment deletion first reads and authorizes the row, deletes the metadata, then removes only a path proven to be below the managed root. Missing source bytes do not prevent metadata deletion, while unexpected filesystem failures produce a bounded storage error and leave metadata available for retry where atomicity permits.

The service and HTTP router own protocol translation. `SQLiteAgentMemory` gains ID-based lifecycle primitives while retaining the CLI's existing name-based compatibility helper. The session delete check and run start path share the RunManager lock or an equivalent lifecycle guard so a new run cannot race a successful delete.

Alternative: allow deletion of a session with a running task. Rejected because the worker could write records after the delete and recreate inconsistent state. Cancellation can be designed separately.

### 4. Treat preview availability and model loading as separate operations

`load_image` continues to validate the attachment registry and return an in-memory `GeneratedImage` for the next model turn. Browser preview uses the HTTP content resource and does not count as a model load. Both paths share ownership, size, media type, readability, and hash validation. A source failure maps to `unavailable` metadata and a stable client message; the response never includes the failing path or raw exception.

### 5. Keep the frontend backend boundary symmetric

Extend `ChartAgentClient` with session deletion, attachment deletion, and content URL access. The Gateway adapter calls the real routes; the mock adapter mutates its in-memory fixture data and provides object URLs for mock attachments. The sidebar's existing operations menu becomes an enabled delete action with a Chinese confirmation dialog. The attachment card gets an explicit delete action and uses a Gateway content URL when `preview_available` is true.

After active-session deletion, the App selects the next session by list position, then the previous one, or clears state if the list is empty. It closes any local subscription, clears pending uploads and selected IDs, and ignores late responses from the deleted session. UI errors are shown only after the server response, so failed deletion does not make local state disagree with Gateway state.

### 6. Migrate compatible legacy files opportunistically

On attachment validation or a controlled service startup migration, a row whose old canonical path is still readable may be copied/moved into the resolved managed root and have its path updated transactionally. The migration only accepts paths that are regular files and pass the same image, size, and hash checks; it never searches arbitrary directories by filename. Rows whose bytes are already gone remain safe metadata with `unavailable` status and can be replaced by a fresh upload.

## Risks / Trade-offs

- [Risk] Users can manually delete or modify files under the application data directory. → Validate existence, type, size, and hash on every content/load operation and expose `unavailable` rather than serving changed bytes.
- [Risk] A process crash between file commit and SQLite commit can leave an orphan file. → Use unique opaque filenames, clean only provable orphan files during an explicit maintenance pass, and never delete files referenced by a live row.
- [Risk] A process crash between SQLite deletion and file cleanup can leave orphan attachment bytes. → Make cleanup idempotent and run a bounded orphan cleanup for managed session directories without touching unknown roots.
- [Risk] Two Gateway instances can access the same database and attachment root. → Retain SQLite busy timeouts, use transactional metadata operations, and document one local Gateway owner per data directory; do not claim multi-process coordination.
- [Risk] An attachment URL contains opaque IDs but remains usable by a local process that can read the session ID. → Keep the server loopback-only, enforce session/attachment ownership and validation, and do not expose paths or credentials.
- [Risk] Existing sessions may contain paths from the old temporary store that cannot be recovered. → Preserve bounded metadata and clearly report unavailable status with re-upload guidance.
- [Risk] The React preview can race session switching or deletion. → Scope URLs and state updates by active session ID, revoke only browser-owned object URLs, and refresh the session after mutations.

## Migration Plan

1. Deploy the Gateway code with the persistent root resolver and content/lifecycle routes. Existing SQLite files remain readable.
2. On first access, preserve valid existing attachment metadata and opportunistically relocate still-readable legacy files; mark missing files unavailable without deleting their rows.
3. Update the React adapter and UI to use the new routes. Existing mock mode remains independent.
4. Verify restart persistence, deletion cascades, content authorization, hash validation, and frontend recovery with the test suites and Gateway smoke flow.
5. Rollback is code-only: old code can read the SQLite metadata, but it will not understand the new persistent-file lifecycle guarantees. Do not delete the new attachment directory during rollback; a subsequent upgraded Gateway can continue using it.

## Open Questions

None. Bulk deletion, undo, quota management, and active-run cancellation are intentionally deferred and do not affect this change's contract.
