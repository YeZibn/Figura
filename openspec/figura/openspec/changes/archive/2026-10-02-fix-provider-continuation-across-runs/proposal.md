## Why

DeepSeek thinking-mode requests that include tools require the reasoning continuation for every earlier assistant turn. Figura already persists continuation against its source Run and response, but the current request projection attaches only current-Run continuation, so a later Run in the same Session can be rejected locally despite complete durable history. The local compatibility check also happens after a Provider attempt is durably claimed, making a request that never reached the service look like a started attempt.

## What Changes

- Resolve provider-private continuation from the exact source Run and response while assembling a later Run's Provider request; keep `SessionHistory` itself provider-neutral and continuation-free.
- Require matching Provider and continuation format wherever the selected Provider policy requires historical continuation. Fail closed on missing or incompatible facts without fabricating continuation, pruning history, disabling reasoning, retrying, or switching Provider.
- Perform local request validation and payload preparation before claiming a durable Provider attempt; report local rejection through the existing bounded Run failure state, and keep the attempt claim before any network dispatch.
- Keep continuation private to trusted Provider request assembly. Add no persistence fields or migration and expose no continuation through public events, API responses, logs, or frontend state.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-memory`: distinguish the neutral complete Session history from provider-specific request projection, including the handling of unavailable or incompatible historical continuation.
- `run-execution-core`: define local Provider request preparation before durable attempt claim while preserving claim-before-dispatch and fail-closed behavior.

## Impact

- Affected Figura code: Agent request assembly and execution, Provider request preparation and dispatch, and their focused tests under `src/figura/` and `tests/`.
- Affected contracts: `session-memory` and `run-execution-core`. Existing `provider-continuation-persistence` already defines source-Run ownership and trusted internal reads; no new stored data shape is planned.
- No public API, frontend, event, or database schema change. Provider selection remains per Run; a selected Provider that cannot consume the complete historical continuation fails locally before attempt claim and dispatch.
