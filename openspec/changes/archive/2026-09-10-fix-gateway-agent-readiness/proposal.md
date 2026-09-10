## Why

Gateway mode currently reports a healthy HTTP service even when the Agent cannot initialize because the project `.env` is not found from the `frontend` working directory. The failure appears only after the first message as a generic `agent_unavailable` error, so the one-step browser and Tauri workflows do not provide an accurate readiness signal or actionable diagnosis.

## What Changes

- Resolve model configuration from a stable project/runtime configuration location instead of relying on the Gateway process current working directory.
- Make the unified browser launcher and Tauri supervisor pass the same configuration contract while preserving the `agent` Conda environment and keeping credentials out of logs and UI payloads.
- Distinguish Gateway HTTP readiness from Agent configuration/readiness, and expose a safe status/error code that the desktop client can render in Simplified Chinese.
- Add coverage for startup from different working directories, missing configuration, valid configuration, Agent initialization failure, and the existing mock/external Gateway behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `desktop-runtime`: Gateway-mode startup and status reporting must reflect both the owned local service and Agent readiness without silently falling back to mock mode.
- `python-gateway`: Health/readiness responses and run failures must distinguish an HTTP-available Gateway from an unavailable Agent while keeping diagnostics bounded and safe.
- `llm-client`: Environment loading must be deterministic across launch working directories and retain explicit-parameter and process-environment precedence.

## Impact

- Python configuration loading in `src/chartagent/client` and Gateway service/health handling.
- Node development launcher and Rust Tauri Gateway supervisor.
- React Gateway status and error mapping in the desktop client.
- OpenSpec contracts and Python, Node, and Rust smoke/unit tests.
