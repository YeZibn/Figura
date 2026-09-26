## Why

Figura has a bounded, stateless `ToolRuntime` and a SQLite Run store, but the Run store currently rejects model responses containing tool calls. Persisting a tool result only after its handler runs leaves a crash window where an external effect may have happened without a durable result; this change gives tool execution an explicit, recoverable record and checkpoint contract before the ReAct loop is added.

## What Changes

- Add a durable tool-execution capability that records ordered tool-call intents, execution attempts, and bounded outcomes in a separately sequenced per-Run tool-fact stream, and advances the Run checkpoint atomically with each committed fact.
- Extend Run execution to accept and persist tool-call model responses when they do not contain provider-private continuation; execute the batch in provider order through the existing `ToolRuntime`.
- Classify an attempt with no committed result as an unknown outcome after recovery. Apply the tool's declared replay effect and a stable logical call identity; do not blindly repeat a call that requires reconciliation.
- Migrate existing SQLite Run data to the new schema while preserving existing Run identities, records, checkpoints, and events.

## Capabilities

### New Capabilities
- `durable-tool-execution`: Persist, execute, and recover an ordered tool-call batch associated with a Run.

### Modified Capabilities
- `run-execution-core`: Support durable tool-call and tool-result facts, checkpoint actions, and recovery state while preserving existing text-only Run behavior.

## Impact

- Affected code: `src/figura/runtime/models.py`, `coordinator.py`, `store.py`, `_codec.py`, `src/figura/tools/contracts.py`, `runtime.py`, and a new durable execution coordinator/owner under `src/figura/runtime/` or `src/figura/tools/`.
- Affected persistence: SQLite schema version, a new ordered tool-execution fact stream, and an additional checkpoint cursor; existing v1 databases require an additive migration that preserves the core record table.
- Affected specifications: new `durable-tool-execution` capability and a delta to `run-execution-core`.
- Provider continuation persistence, Provider request retry/recovery, the full Agent ReAct loop, domain chart tools, public tool events, and frontend/Gateway presentation remain out of scope.
