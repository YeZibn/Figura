# Figura

Figura is a local chart analysis workspace with a freely planned, tool-capable Agent mode. The current Python implementation keeps the `chartagent` module name for compatibility. Use the Conda environment named `agent` for all project commands:

```bash
conda run -n agent python -m pytest -q
conda run -n agent python -m chartagent --agent
```

## Desktop client

The desktop client is a Tauri 2 shell around a React + TypeScript + Vite workspace. During UI development, start the browser client from the frontend directory:

```bash
cd frontend
npm install
npm run dev
```

The Vite app is available at http://127.0.0.1:1420/. To run the Tauri development window after installing the Rust toolchain, use `npm run tauri:dev` from `frontend/`. The desktop client uses mock data by default and does not silently fall back to mock data when Gateway mode is explicitly enabled.

### Local Python Gateway

The second desktop milestone adds a loopback Python Gateway for named sessions
and completed text runs. Start the Gateway and the Gateway-mode browser client
together from `frontend/`:

```bash
npm run dev:gateway
```

The launcher uses `conda run -n agent python -m chartagent.gateway`, waits for
`/api/v1/health`, starts Vite in explicit Gateway mode, and stops both process
groups it created when you press Ctrl-C before the launcher exits. A frontend
bind failure also cleans up the Gateway created for that attempt without
terminating an unrelated listener. Plain `npm run dev` remains the offline
mock/frontend-only workflow. From the repository root, the equivalent
one-line command is `npm --prefix frontend run dev:gateway`.

To verify the complete npm signal and port-release lifecycle, run
`npm run smoke:launcher` from `frontend/`. This uses isolated ports and does
not replace the regular static `npm run smoke` checks.

The service listens on `127.0.0.1` and exposes versioned routes under `/api/v1`.
The desktop panel can select PNG, JPEG, GIF, and WebP images, preview them,
upload them to the active session, delete registered attachments, and select
valid IDs for the next message. The Gateway keeps uploaded bytes in a
persistent application-owned directory and SQLite stores only safe attachment
metadata and references. By default, attachments are stored beside the
configured session database under `attachments/` (or under
`~/.chartagent/attachments/` when no data directory is configured);
`CHARTAGENT_ATTACHMENT_DIR` can override the location. A valid source remains
available after a Gateway restart. If a source is missing or its hash changes,
the workspace marks it unavailable and offers re-upload recovery. Registration
does not send image bytes to the model. The Agent decides whether to call
`load_image` when visual inspection is useful.

The Gateway provides these attachment and lifecycle routes in addition to the
session read/write operations:

```text
DELETE /api/v1/sessions/{session_id}
DELETE /api/v1/sessions/{session_id}/attachments/{attachment_id}
GET    /api/v1/sessions/{session_id}/attachments/{attachment_id}/content
```

Session deletion is permanent and removes its runs, records, attachment
metadata, and managed source files. The Gateway rejects deletion while the
session has an active Agent run. The desktop client asks for confirmation before
deleting a session or attachment and selects a neighboring session after
successful deletion.

When running the Tauri client in Gateway mode, use the dedicated alias. Tauri
owns the local Gateway child process and waits for `/api/v1/health` before
exposing the workspace:

```bash
npm run tauri:dev:gateway
```

The alias sets `CHARTAGENT_MODE=gateway` and `VITE_CHARTAGENT_MODE=gateway`.
The development launcher uses `conda run -n agent python -m chartagent.gateway`
without hard-coding a machine-specific Python path. Do not run both launchers
against the same port. A pre-existing compatible
Gateway can be used with `CHARTAGENT_GATEWAY_EXTERNAL=1`; the Tauri client will
not terminate that process. For a packaged or custom runtime, set
`CHARTAGENT_GATEWAY_EXECUTABLE` and provide a JSON string array in
`CHARTAGENT_GATEWAY_ARGS`.

The Gateway keeps the synchronous `POST /api/v1/sessions/{id}/messages`
operation for compatibility. The desktop live-run path uses:

```text
POST /api/v1/sessions/{session_id}/runs
GET  /api/v1/sessions/{session_id}/runs/{run_id}/events
GET  /api/v1/sessions/{session_id}/runs/{run_id}/observations/{observation_id}
GET  /api/v1/sessions/{session_id}/runs/{run_id}/artifacts/{artifact_id}
```

The event stream is bounded SSE and includes model turns, tool calls, tool
results, visual-observation metadata, generated-chart metadata, final answers,
and failures. Temporary visual evidence is available through short-lived
opaque observation IDs. User-facing charts created by `render_chart` use a
separate `artifact_<id>` reference and the `/artifacts/` route, so their PNG
bytes are persisted for the configured run-retention period and remain scoped
to the owning session. Event JSON and durable session memory never contain
image bytes, credentials, provider raw responses, or unbounded trace content.
Run cancellation is not part of this milestone. Gateway runs also persist
bounded execution history separately from model conversation records. The
client restores run summaries and events after reload, replays from an event
cursor after reconnect, joins tool calls/results/visual observations by
`call_id`, and renders generated charts with preview, metadata, download, or an
explicit unavailable state. Final answers are rendered as safe Markdown; the
original bounded source remains available in the answer panel.

Additional run-history routes are:

```text
GET    /api/v1/sessions/{session_id}/runs
GET    /api/v1/sessions/{session_id}/runs/{run_id}
GET    /api/v1/sessions/{session_id}/runs/{run_id}/events?after={sequence}
```

## Agent sessions

Without `--session`, Agent history and attachment references are process-local. Named sessions are opt-in and stored in SQLite at `$CHARTAGENT_DATA_DIR/sessions.db`, or at `~/.chartagent/sessions.db` when the variable is unset.

```bash
conda run -n agent python -m chartagent --agent --new-session demo
conda run -n agent python -m chartagent --agent --session demo
conda run -n agent python -m chartagent --agent --list-sessions
conda run -n agent python -m chartagent --agent --delete-session demo
```

`--delete-session` asks for confirmation and removes only local session state. It never deletes source image files. `--new-session` refuses to overwrite an existing session.

## Images and tools

In the Agent REPL, enter an image as `@/path/to/chart.png` or `@"/path with spaces/chart.png"`. The CLI registers the file and sends the model an opaque `att_...` ID plus safe metadata. It does not eagerly send image bytes. The model can call `load_image(attachment_id)` whenever visual inspection is useful, and can pass the same ID to `extract_text` or `measure_bars`. Every load validates ownership, file availability, size, media type, and content hash.

Tool-generated overlays are returned as in-memory visual observations for the next model turn. Their bytes, source-image bytes, provider reasoning, raw responses, credentials, and trace events are not persisted in session memory.

To redraw structured data, the Agent can pass an existing or newly assembled
`ChartSpec` to the optional `render_chart` tool. The tool validates the shared
specification and supports `bar`, `line`, `pie`, and `scatter` charts with
bounded PNG output. A successful call returns structured metadata plus visual
evidence for the next model turn; the Gateway separately stores the generated
PNG as a `generated_chart` artifact for the desktop preview and download. A
rendering or artifact-limit failure remains a structured tool error and does
not prevent a text answer.

## Trace mode

Use `--trace` with `--agent` to inspect model turns, tool calls, results, visual observations, and the final answer. Add `--trace-reasoning` only when the provider supplies reasoning and it is appropriate to display it. Trace output is diagnostic output; it is not stored in named sessions.
