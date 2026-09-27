## Why

Figura has durable Runs, provider adapters, tool validation, and ordered tool execution, but no owner that repeatedly connects model decisions to tool observations and final answers. This change adds a bounded text-only ReAct execution path while preserving the existing Run facts as the source of truth and preventing an ambiguous provider request from being sent again after recovery.

## What Changes

- Add an internal Agent execution capability that assembles provider history from committed Run facts, sends a model request, executes the returned tool batch in provider order, and continues until a valid final answer or a bounded terminal failure.
- Persist a provider-attempt marker before each external model request and atomically associate its terminal outcome with the response or safe failure, so restart never guesses whether to resend.
- Add a request/round budget of 8 provider attempts and 32 logical tool calls per Run; enforce provider request limits while retaining complete interaction boundaries.
- Keep this change text-only, non-streaming, and internal. Use a fixed v1 instruction asset and a test-only fake Provider/ToolRegistry; do not add production chart tools, attachment handling, Gateway/frontend APIs, cross-Run memory, or implicit retries/fallback.

## Capabilities

### New Capabilities
- `agent-react-execution`: checkpoint-driven ReAct loop, history assembly, bounded budgets, and terminal behavior.

### Modified Capabilities
- `run-execution-core`: durable provider-attempt state, atomic checkpoint transitions, and fail-closed recovery when a model request has an unknown outcome.

## Impact

- Affected areas: `src/figura/agent/` (new request builder and executor), `src/figura/runtime/` (provider-attempt persistence and coordinator/store transitions), provider request projection, and focused Python regression tests.
- SQLite storage requires a backward-compatible schema migration from the current version; existing Runs and provider continuations must remain readable.
- No public HTTP/SSE contract, frontend behavior, production tool catalog, provider/model allowlist, or provider adapter behavior is added or changed.
