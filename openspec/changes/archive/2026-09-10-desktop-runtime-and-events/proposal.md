## Why

The desktop workspace can already manage sessions and image attachments, but a real Gateway run is still a synchronous request whose intermediate Agent activity is invisible to the user. Tauri also does not yet own the Python Gateway lifecycle, so the desktop client is not self-contained and cannot reliably report whether its local runtime is ready.

## What Changes

- Add a Tauri-managed local Gateway runtime with explicit startup, health, readiness, and shutdown states.
- Add a single-command development launcher that starts the Conda `agent` Gateway and the Gateway-mode React client together, waits for readiness, and cleans up both processes on exit.
- Add a Gateway run protocol that exposes a stable run identifier and a bounded server-sent event stream for model turns, tool calls, tool results, visual observations, final answers, and failures.
- Preserve the existing sanitized Agent trace boundary and keep reasoning, credentials, raw provider payloads, image bytes, and unbounded details out of the desktop event stream.
- Update the React workspace to consume live Gateway events, render execution details and visual observations in chronological order, and distinguish connecting, running, completed, failed, and unavailable states.
- Keep mock mode and the existing synchronous Gateway contract available for development or compatibility where practical.
- Keep mock mode opt-in for the unified launcher; an unavailable Gateway must be reported instead of silently selecting mock data.
- Keep Conda environment `agent` as the required development and test runtime; do not hard-code a machine-specific Conda path into the desktop client.

## Capabilities

### New Capabilities

- `desktop-runtime`: Tauri-managed lifecycle and readiness boundary for the local Python Gateway.

### Modified Capabilities

- `python-gateway`: Add observable Agent run lifecycle and bounded event streaming while preserving local-only and safe response boundaries.
- `desktop-client`: Add live run state, execution event, visual observation, and failure rendering backed by the Gateway event contract.

## Impact

- Affects `src-tauri` process management and Tauri configuration, the Python Gateway service/server/protocol, and the React client boundary, state management, and execution-detail components.
- Adds a development process launcher and package scripts for starting the Gateway and React client as one supervised group, plus matching Tauri Gateway-mode script aliases.
- Reuses `Agent` and `TraceEmitter` events rather than changing model history or the CLI trace output.
- Adds a local streaming transport dependency or implementation for the Gateway and corresponding frontend event handling.
- Requires Python Gateway, launcher lifecycle, frontend smoke/build, Tauri development, and end-to-end local runtime verification in the `agent` Conda environment where Python is involved.
