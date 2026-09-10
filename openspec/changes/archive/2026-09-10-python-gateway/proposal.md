## Why

The desktop client currently operates entirely on deterministic mock data while the real ChartAgent, session memory, and tool-capable execution loop are available only through the CLI. A local gateway is needed to make persistent Agent sessions and completed text runs available to the desktop client through a stable, browser-compatible boundary.

## What Changes

- Add a loopback-only Python HTTP/JSON gateway for listing, creating, and reading named Agent sessions.
- Add a synchronous message endpoint that runs the existing `Agent` against a named session and returns a normalized completed result for the client.
- Define a versioned, JSON-safe gateway contract that maps persisted session and completed-run data into client-facing session and conversation records.
- Provide explicit, bounded error responses for invalid input, missing sessions, duplicate session names, unavailable provider configuration, and Agent-run failures.
- Add a frontend gateway adapter that implements the existing client boundary while retaining the mock adapter as the default offline mode.
- Add repeatable API and frontend-adapter verification without requiring Tauri, Rust, a provider credential, attachment upload, or an event-stream connection.

## Capabilities

### New Capabilities

- `python-gateway`: Provide a local, loopback HTTP/JSON boundary for the desktop client to operate named Agent sessions and completed text runs.

### Modified Capabilities

None. The gateway adapts existing Agent, memory, attachment, and trace behavior without changing their existing contracts.

## Impact

- Adds a Python gateway module and a minimal local HTTP serving entry point using the existing Conda `agent` environment.
- Adds JSON request/response schemas and tests for session and message operations.
- Adds a real frontend client adapter and development configuration for selecting mock or gateway mode.
- Reuses `Agent`, `SQLiteAgentMemory`, the existing tool registry, and existing configuration loading; it does not expose SQLite directly to the frontend.
- Does not add real attachment upload, browser-visible attachment previews, streamed tool events, Tauri sidecar lifecycle management, remote binding, authentication, or packaging.
