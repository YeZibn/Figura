## Why

The current Run contributes to the 80% request-occupancy trigger, but its committed conversation process is excluded from both the `C/10` raw-history selection and summary coverage. A long Run therefore cannot reclaim its own older context before it finishes, even when each new request approaches the configured context capacity.

## What Changes

- Include the active Run's committed, complete interactions in the chronological history used to choose the `C/10` raw tail and summary coverage.
- Allow a summary checkpoint to cover a stable prefix of the active Run while keeping its exact original user input intact in the ordinary request and supplying it separately as summary context.
- Keep the newest complete interactions raw and leave in-flight Provider work, uncommitted records, and incomplete tool-call batches outside summary coverage.
- Bind active-Run coverage to the Run's committed record/tool prefix so retries and recovery reuse the same source slice and request identity.
- Continue deriving raw-history and approximate summary targets independently from the selected Provider capacity; count the full rebuilt request, including the active input, in the ordinary occupancy estimate.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-context-compaction`: permit incremental compaction of the active Run's committed process prefix while retaining its original input and incomplete work.

## Impact

- Agent history selection, summary-request construction, and ordinary-request projection under `src/figura/agent/`.
- Runtime checkpoint ownership, compaction-operation validation, and recovery under `src/figura/runtime/`.
- The main `session-context-compaction` specification and its focused Agent/Runtime tests.
- No new user-facing tool or API is intended; the durable checkpoint contract and validation boundaries must be updated to represent an active Run prefix safely.
