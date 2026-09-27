## Why

Figura's Provider adapters already return provider-private continuation data needed to continue some thinking/tool interactions, but Run persistence currently rejects those responses and cannot reconstruct the exact provider history after restart. Persisting the private payload with the Run lets later execution rounds resume from committed model and tool facts without exposing provider reasoning through public Run data.

## What Changes

- Add a private, versioned durable continuation record linked to its Run and originating model response.
- Commit a continuation reference atomically with the model response, tool-call intents, and checkpoint; allow valid continuations on both text and tool-call responses.
- Add an internal read path that resolves the exact continuation for history reconstruction and fails closed on missing, mismatched, or unsupported data.
- Keep continuation payloads out of public Run summaries, lifecycle events, ordinary logs, and error messages; retain them for the Run lifecycle.
- Add an additive SQLite migration and preserve existing Runs and records.

## Capabilities

### New Capabilities

- `provider-continuation-persistence`: privately persist, validate, retain, and resolve provider continuation data associated with committed Run model responses.

### Modified Capabilities

- `run-execution-core`: atomically commit a valid continuation reference with model response progress and reconstruct it as part of committed Run state.
- `durable-tool-execution`: permit a model response with tool calls to commit when its provider-private continuation is valid and durably associated with that response.

## Impact

- Affected code: `src/figura/providers/`, `src/figura/runtime/models.py`, `src/figura/runtime/_codec.py`, `src/figura/runtime/coordinator.py`, and `src/figura/runtime/store.py`.
- Affected persistence: additive SQLite schema migration and model-response payload version compatibility.
- Affected contracts: internal RunState/history reconstruction only; no public event, Gateway, CLI, or UI schema expansion.
- No Provider API, retry, fallback, or ReAct scheduler is added by this change.
