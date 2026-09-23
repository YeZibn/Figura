## Why

Generated Chart Review currently stores the same lifecycle in both `ChartReviewManager` and `ReviewCoordinator`, with `GeneratedChartReviewAdapter` copying state between them. The Agent reads these sources for different decisions, and the deterministic artifact audit currently runs in both the Agent flow and `ChartReviewManager.process()`. This creates avoidable state divergence, repeated work, and noisy review traces.

## What Changes

- Make the generated candidate review lifecycle have one authoritative owner covering candidate identity, review result, repair attempt, publication state, and idempotency.
- Derive the execution gate from that canonical review state; remove the separately mutable generated-review records and gate map.
- Run deterministic artifact checks once in the review operation, then run the required tool-free VLM review once and apply both results to the same candidate state.
- Persist and restore the canonical review state at recovery boundaries. Do not dual-read or dual-write the old `reviewState` plus independently restored `executionGate` checkpoint shape; reject unsupported legacy review state explicitly and fail closed.
- Emit one canonical review lifecycle for each candidate attempt. Keep bounded technical evidence available in trace details without exposing internal checks as separate user-facing review steps.
- Remove the generated-review adapter/coordinator path and review adapters or exports that have no active production caller, including the unused measurement review adapter, after migrating their tests to the canonical interfaces.

The existing review behavior remains intact: failed candidates stay unpublished, repair remains model-directed and bounded, stale results are rejected, and collection children retain their parent/child lineage.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `review-gates`: make generated-chart review the only shared review lifecycle, define its single authoritative state owner and derived gate, and remove the unused measurement-review envelope contract. Measurement quality remains advisory and is not changed here.

## Impact

- Affected code: `src/chartagent/review/`, Agent review orchestration and recovery, Gateway checkpoint/read-model projection, and review-related tests.
- The generated review state and execution gate will have a single source of truth; API and event gate fields remain derived projections.
- Old checkpoints using the dual review-state layout will not be silently interpreted. Recovery must report an explicit unsupported review-state version and preserve the publication fail-closed invariant.
- No provider, review policy, ChartSpec, or measurement-decision behavior is changed by this change. Existing `vlm-chart-review` and `unified-decision-review-timeline` contracts remain unchanged.
