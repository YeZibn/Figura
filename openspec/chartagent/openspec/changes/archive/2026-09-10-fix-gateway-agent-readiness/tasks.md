## 1. Stabilize runtime configuration loading

- [x] 1.1 Extend Python environment loading to honor an explicit environment-file argument, `CHARTAGENT_ENV_FILE`, and a stable project fallback while preserving process-environment precedence and credential redaction.
- [x] 1.2 Add Conda-backed unit coverage for configuration precedence and equivalent results when invoked from the repository root and `frontend` directories.

## 2. Expose Gateway and Agent readiness separately

- [x] 2.1 Add a bounded Agent readiness probe and nested health status that distinguishes HTTP availability from missing or invalid provider configuration without exposing secrets or raw exceptions.
- [x] 2.2 Preserve the existing `agent_unavailable` run contract while attaching only safe reason codes and keeping failed runs out of completed session history.
- [x] 2.3 Extend Gateway tests for healthy configuration, missing configuration, safe health payloads, safe run failures, and prior-history preservation.

## 3. Align browser and Tauri startup paths

- [x] 3.1 Update the unified Node launcher to resolve the project environment file, pass `CHARTAGENT_ENV_FILE` to the Conda Gateway child, and retain existing process-group cleanup and port-protection behavior.
- [x] 3.2 Update the Tauri development alias and Rust supervisor to inherit the same environment-file contract and represent Gateway HTTP status separately from Agent readiness.
- [x] 3.3 Add Node and Rust contract coverage for environment propagation, health parsing, missing Agent configuration, external Gateway ownership, and existing startup/shutdown behavior.

## 4. Surface actionable status in the desktop client

- [x] 4.1 Add a Gateway health client model and fetch the health payload when Gateway mode starts, while keeping mock mode independent of all Gateway requests.
- [x] 4.2 Render separate Gateway and Agent states in the Simplified Chinese UI and map safe reason codes to configuration guidance without falling back to mock data.
- [x] 4.3 Update frontend smoke contracts and runtime types for the new health status and error mapping.

## 5. Verify the integrated workflow

- [x] 5.1 Run the Python test suite through `conda run -n agent` and verify all configuration, Gateway, and regression tests pass without printing credential values.
- [x] 5.2 Run frontend smoke, build, launcher smoke, and launcher lifecycle checks from the documented workflow.
- [ ] 5.3 Run the Tauri Rust test suite and manually verify Gateway mode from both the repository root and `frontend`, including the missing-configuration diagnosis and normal Agent startup path.
