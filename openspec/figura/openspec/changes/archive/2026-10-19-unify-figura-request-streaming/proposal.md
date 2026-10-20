## Why

Figura currently sends ordinary Agent calls and context-compaction summaries through separate non-streaming paths. This makes long waits opaque, leaves timeout and retry behavior inconsistent, and prevents one durable attempt record from explaining where a request stalled. A single streaming Provider contract will make every model request observable while preserving atomic Agent, tool, continuation, and checkpoint commits.

## What Changes

- **BREAKING** Replace the Provider request contract with one streaming-only request and normalized event contract for all configured Providers and all request purposes.
- Route ordinary Agent turns, tool-call turns, and context-compaction summaries through the same streaming transport, timeout classification, cancellation, retry, and attempt recording.
- Separate connection establishment, request transmission, response opening, stream activity, and total elapsed time. Do not impose a total generation deadline; continue while the transport remains live and report prolonged inactivity without treating it alone as a failure.
- Persist phase-level Provider attempt diagnostics and retry lineage. Keep partial output transient; commit a normalized response, continuation, tool-call batch, or compaction checkpoint only after a valid terminal stream event.
- Stream user-visible assistant text through Gateway as transient deltas and publish coarse durable Provider status transitions. Never expose reasoning or partial tool arguments, and never persist every token as a Run event.
- Replace the frozen request binding and strict codecs with one canonical streaming contract. Use a direct schema migration for stored Runtime data; preserve completed history and close incompatible in-flight attempts as outcome-unknown rather than keeping a legacy execution path.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `model-provider`: define the streaming-only Provider request and normalized event contract.
- `provider-request-retries`: unify retry, unknown-outcome, cancellation, and request-binding rules across all Provider request purposes.
- `run-execution-core`: record phase-level Provider attempt lifecycle and commit only complete responses.
- `provider-continuation-persistence`: bind continuation data atomically to a completed streamed response.
- `session-context-compaction`: use the shared stream while preserving summary validation and atomic checkpoint installation.
- `figura-web-gateway`: expose durable Provider status and transient assistant text deltas.
- `figura-web-client`: render transient answer deltas and recover to canonical Run state after reconnect.

## Impact

- Provider request assembly, adapters, transport, failure classification, and retry coordination under `src/figura/providers/` and `src/figura/agent/`.
- Runtime records, SQLite schema and migration, codecs, repositories, and recovery under `src/figura/runtime/`.
- Gateway SSE contracts and the frontend Figura event controller, protocol types, and conversation view.
- Provider, Agent, Runtime, Gateway, and frontend tests. No new third-party dependency is required.
