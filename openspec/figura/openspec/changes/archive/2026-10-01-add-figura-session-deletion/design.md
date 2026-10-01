## Context

See `proposal.md` for the user-facing need and `specs/` for the behavior contract. Figura mode explicitly disables the shared sidebar's Session deletion action. Its own client and Gateway expose only Session list/read/create operations. Runtime, Sources, and render PNGs share one local data root and SQLite database, but their data has separate owners. Runtime facts and Panel rows currently have immutable-delete triggers; foreign keys use `ON DELETE RESTRICT`.

## Goals / Non-Goals

**Goals:**

- Permanently remove one terminal Session and all of its owned Runtime rows and private image files.
- Keep per-Session deletion isolated and preserve record immutability while a Session exists.
- Make filesystem cleanup recoverable when a process stops during deletion.
- Keep the ChartAgent client and workspace behavior unchanged.

**Non-Goals:**

- Cancel, interrupt, or wait for a running Run as part of deletion.
- Add undo, soft deletion, account-wide deletion, or deletion of individual Runs.
- Change the format of Session messages or the ordinary attachment deletion rule.

## Decisions

### Delete a Session only after all of its Runs are terminal

`DELETE /sessions/{sessionId}` returns `204` after a successful deletion, `404` for an unknown Session, and `409` while any owned Run is `running`. Runtime checks the Run states inside the deletion write transaction; a UI status check is not authoritative. Deletion does not interrupt a queued or executing Run. This keeps the asynchronous Dispatcher from committing facts into a removed aggregate.

### Coordinate the purge at the application boundary

Add one Figura Session-deletion use case composed by `bootstrap.py` and called by `FiguraGatewayApplication`. It coordinates Runtime and Sources repositories plus the attachment, Panel, and ChartRender file owners. The HTTP route does not issue SQL, and no single domain takes ownership of another domain's files. Repository deletion helpers receive the same active SQLite connection so relational cleanup commits as one transaction.

The use case first reads the Session's owned file identities and all durable `render_chart_figure` call identities while holding the SQLite write lock. It then creates a temporary `session_deletion_scopes` row for the Session. The schema migration changes immutable-row DELETE triggers to permit deletion only when the owning Session has this scope; immutable UPDATE triggers remain unconditional. The scope is transaction-local in practice: it is inserted and removed inside the same purge transaction, and is not a Session field or public model.

The transaction removes child rows in foreign-key order: idempotency mappings and Run facts (Provider attempts, continuations, checkpoints, events, tool facts, and records), Panels and attachment metadata, Runs, the deletion scope, then the Session. A direct deletion of an isolated immutable row has no scope and remains rejected. If SQL work fails, SQLite rolls back the scope and all row changes.

### Stage private files before deleting their metadata

Each file owner moves the Session's files into a private `session-trash/<session_id>/` staging tree while the deletion transaction is open. The tree retains fixed owner subdirectories and server-derived filenames for attachments, Panels, and render PNGs; IDs are validated and no caller-controlled path is used. If staging or the database transaction fails, the use case restores staged files before returning an error.

After the database commits, the use case removes the staging tree. If the process stops or final unlink fails, startup reconciliation checks the Session row: if it still exists, staged files are restored; if it no longer exists, the staged tree is permanently removed. The trash directory is private and is never addressable through HTTP, Provider requests, or tool results. This avoids claiming cross-filesystem/SQLite atomicity while keeping partial deletion inaccessible and recoverable.

### Reuse the Figura client and shared list control

Add `deleteSession` to `FiguraClient` and `sessions.remove` to `FiguraWorkspaceApi`, implemented by the Figura adapter. Turn on the existing optional per-row delete control in `FiguraApp` and use a confirmation that names the Session and lists the data being removed. Keep the delete request inside the API adapter; React components do not call Gateway transport directly.

On success, remove only the deleted row. If it was active, close its Run subscription, clear its draft/selection and preview URLs, then select the next available Session (or previous when deleting the last row); if none remain, render the empty state. A `409` leaves the row and current conversation intact and displays the safe Gateway message. Deleting a non-active Session does not disturb the selected Session.

### Migrate existing stores forward only

Bump SQLite schema from v7 to v8. The migration adds the empty deletion-scope table and replaces the existing immutable DELETE triggers with scoped guards; it does not rewrite existing Sessions, Runs, or facts. There is no automatic downgrade after a v8 database has accepted a permanent deletion; restoring a pre-migration binary requires restoring a pre-migration data backup.

## Risks / Trade-offs

- [Filesystem rename and SQLite commit cannot be one atomic operation] → Stage files before the database commit, restore on rollback, and reconcile staged files on startup by checking whether the Session still exists.
- [A Session may have many Runs and image files] → Keep one Session-scoped write transaction and derive file identities from owned metadata and committed render tool-call facts; do not scan or alter other Session resources.
- [Permanent deletion cannot be undone] → Require explicit confirmation naming the Session and all content categories removed.
- [Old binaries cannot read a newer schema] → Use the repository's forward-only migration policy and retain the existing local data backup guidance.
- [A Run may be queued or recovering while the user clicks delete] → Treat persisted `running` status as a conflict and make Runtime recheck it under the write lock.
