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
and completed text runs. Start it with the Conda `agent` environment, then run
the browser client in Gateway mode:

```bash
conda run -n agent python -m chartagent.gateway --port 8765
cd frontend
VITE_CHARTAGENT_MODE=gateway npm run dev
```

The service listens on `127.0.0.1` and exposes versioned routes under `/api/v1`.
The desktop panel can select PNG, JPEG, GIF, and WebP images, preview them
locally, upload them to the active session, and select registered IDs for the
next message. The Gateway keeps uploaded bytes in a temporary, process-owned
directory and SQLite stores only safe attachment metadata and references. A
Gateway restart can make the source unavailable; upload the image again in that
case. Registration does not send image bytes to the model. The Agent decides
whether to call `load_image` when visual inspection is useful. Runtime event
streaming and Tauri-managed Python processes remain later milestones.

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
