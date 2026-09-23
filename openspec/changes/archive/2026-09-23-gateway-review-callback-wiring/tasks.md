## 1. Make the Gateway runtime contract explicit

- [x] 1.1 Define the Gateway runtime-factory contract with explicit per-run parameters for `execution_gate_sink`, `candidate_input_sink`, and `candidate_input_resolver`.
- [x] 1.2 Update the default Gateway runtime builder to accept and forward all review lifecycle integrations to `create_agent_runtime`.
- [x] 1.3 Remove signature-based silent keyword filtering and update injected runtime factories and test doubles to satisfy the explicit contract.

## 2. Distinguish integration failures from storage failures

- [x] 2.1 Validate that required Gateway review integrations are available before Agent execution and map missing wiring to a bounded runtime-integration failure.
- [x] 2.2 Preserve fail-closed candidate behavior when the configured persistence callback is actually invoked and storage fails; do not classify missing wiring as `candidate_storage_failure`.
- [x] 2.3 Verify candidate review-input resolution and execution-gate updates use the same per-run runtime dependencies during normal execution and recovery.

## 3. Add Gateway-path regression coverage

- [x] 3.1 Add focused tests proving the default runtime forwards candidate persistence, review-input resolver, and execution-gate callbacks.
- [x] 3.2 Add an integration regression using a temporary Gateway database and stubbed model/reviewer to verify a rendered candidate is stored with its exact ChartSpec, reaches review, and remains unpublished until review passes.
- [x] 3.3 Add failure-path coverage distinguishing missing integration from real storage failure and confirming both prevent publication with the appropriate bounded cause.
- [x] 3.4 Run the focused Gateway/review tests and the Python test suite in the `agent` Conda environment.
