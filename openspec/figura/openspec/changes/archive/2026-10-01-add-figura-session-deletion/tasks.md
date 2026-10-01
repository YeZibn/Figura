## 1. Runtime aggregate deletion

- [x] 1.1 Add the v7-to-v8 migration and transaction-scoped Session deletion authorization while preserving unconditional immutable-update guards.
- [x] 1.2 Add one Runtime deletion operation that rechecks Session existence and rejects any `running` Run under the SQLite write lock.
- [x] 1.3 Delete all Runtime-owned rows for the Session in foreign-key order in the same transaction; keep isolated immutable-fact deletion rejected.
- [x] 1.4 Add migration, terminal Session purge, running-Run rejection, cross-Session isolation, and transaction rollback regression coverage.

## 2. Private file staging and recovery

- [x] 2.1 Add Session-scoped staging, restore, and final cleanup operations to attachment, Panel, and ChartRender file owners using server-derived paths.
- [x] 2.2 Add startup reconciliation that restores staged files when the Session remains and removes staged files after the Session row has been deleted.
- [x] 2.3 Gather attachment IDs, Panel IDs, and durable render `(run_id, call_id)` identities before Runtime facts are removed.
- [x] 2.4 Add file-storage regression coverage for partial staging, database rollback, committed deletion cleanup, restart recovery, and preservation of other Sessions' files.

## 3. Gateway deletion use case

- [x] 3.1 Compose a Figura Session-deletion use case from Runtime, Sources, and render storage without placing persistence SQL in the HTTP route.
- [x] 3.2 Add `DELETE /sessions/{sessionId}` with `204` success, bounded `404` for unknown Sessions, and bounded `409` for Sessions with a running Run.
- [x] 3.3 Ensure failures before database commit restore staged files and leave the Session readable; ensure committed deletions are no longer exposed by Session, Run, attachment, Panel, timeline, or render routes.
- [x] 3.4 Add Gateway regression coverage for response codes, origin guard, active-Run rejection, Session isolation, and deletion recovery behavior.

## 4. Figura client and workspace control

- [x] 4.1 Add `deleteSession` to `FiguraClient` and `sessions.remove` to `FiguraWorkspaceApi` without changing ChartAgent or mock client contracts.
- [x] 4.2 Enable the existing per-Session delete control in Figura mode and require confirmation naming the Session and the content categories removed.
- [x] 4.3 On success, remove the deleted row; when it was active, close subscriptions, clear local previews and draft state, and select a remaining Session or show the empty state.
- [x] 4.4 Keep the Session and current view intact on cancellation or Gateway failure, including the running-Run conflict response.
- [x] 4.5 Add Figura client and frontend regression coverage for selected/non-selected deletion, cancellation, empty state, and bounded error display.

## 5. Verification

- [x] 5.1 Run the targeted Figura Runtime, Sources, render-storage, and Gateway regression suites in the `agent` Conda environment, then run the full Python test suite.
- [x] 5.2 Run `npm run build` and `npm run smoke` from `frontend/` and resolve failures related to Session deletion.
- [x] 5.3 Run `git diff --check` and verify the v7 migration preserves existing data, active Runs cannot be deleted, and no files or facts from another Session are removed.
