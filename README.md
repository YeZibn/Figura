# ChartAgent

ChartAgent provides a plain conversation mode and a freely planned, tool-capable Agent mode. Use the Conda environment named `agent` for all project commands:

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
`/api/v1/health`, starts Vite in explicit Gateway mode, and stops only the two
processes it created when you press Ctrl-C. Plain `npm run dev` remains the
offline mock/frontend-only workflow. From the repository root, the equivalent
one-line command is `npm --prefix frontend run dev:gateway`.

The service listens on `127.0.0.1` and exposes versioned routes under `/api/v1`.
The desktop panel can select PNG, JPEG, GIF, and WebP images, preview them
locally, upload them to the active session, and select registered IDs for the
next message. The Gateway keeps uploaded bytes in a temporary, process-owned
directory and SQLite stores only safe attachment metadata and references. A
Gateway restart can make the source unavailable; upload the image again in that
case. Registration does not send image bytes to the model. The Agent decides
whether to call `load_image` when visual inspection is useful.

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
```

The event stream is bounded SSE and includes model turns, tool calls, tool
results, visual-observation metadata, final answers, and failures. Generated
visual evidence is available only through short-lived opaque observation IDs;
event JSON and durable session memory never contain image bytes, credentials,
provider raw responses, or unbounded trace content. Run cancellation is not
part of this milestone.

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

## Trace mode

Use `--trace` with `--agent` to inspect model turns, tool calls, results, visual observations, and the final answer. Add `--trace-reasoning` only when the provider supplies reasoning and it is appropriate to display it. Trace output is diagnostic output; it is not stored in named sessions.
