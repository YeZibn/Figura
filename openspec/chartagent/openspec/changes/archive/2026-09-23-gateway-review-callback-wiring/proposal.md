## Why

`test2` shows that chart rendering can succeed while the default Gateway runtime loses the callbacks needed to persist and resolve the candidate for mandatory review. The run then fails with `candidate_storage_failure` before semantic review can use the stored ChartSpec and image. Gateway-managed runs must preserve this review integration end to end, and required callback wiring must not disappear silently.

## What Changes

- Make the per-run Gateway runtime integration contract explicit for candidate persistence, candidate review-input resolution, and execution-gate updates.
- Forward these required operations through the default Gateway runtime into the Agent runtime; do not silently discard them based on runtime-factory signature inspection.
- Keep genuine candidate-storage failures fail-closed, while reporting missing runtime wiring as an integration/configuration failure rather than misclassifying it as a storage write failure.
- Add Gateway-path regression coverage for candidate persistence, review-input resolution, gate propagation, and genuine storage failure.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `python-gateway`: require the default Gateway-managed Agent runtime to preserve the candidate-review and gate lifecycle operations needed by chart-generation runs.

## Impact

- Affected code: `src/chartagent/gateway/service.py`, `src/chartagent/runtime/factory.py`, and Gateway/review integration tests.
- Existing review behavior remains fail-closed when durable candidate storage actually fails; this change fixes missing callback delivery and makes that failure boundary explicit.
- No HTTP/SSE field changes, new review states, or frontend changes are included.
