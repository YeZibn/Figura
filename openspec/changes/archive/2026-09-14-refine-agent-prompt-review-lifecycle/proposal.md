## Why

The tool contract and generated-chart review gate are already implemented. The remaining gap is that the Agent prompt, review-gate context, lifecycle event payloads, and desktop presentation do not consistently explain the existing behavior. This can make a successful tool call, completed review, and published chart appear equivalent.

## What Changes

- Restructure the default Agent system prompt around evidence use, tool selection, generated-chart review, and final-answer boundaries.
- Keep the review gate as an obligation rather than introducing explicit Agent phases, and provide bounded structured context for pending candidates.
- Make the existing review tool available through normal runtime setup without changing its completed definition contract.
- Separate tool execution, candidate/review, and publication status in lifecycle projections and client rendering.
- Correct `chart_review_started`, complete lifecycle labels, and connect the existing bilingual tool catalog to the execution timeline.
- Preserve existing tool definitions, parameter schemas, tool names, event kinds, artifact references, and review algorithms.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `agent-loop`: static prompt, review-obligation context, stable review-tool availability, and final-answer gate.
- `execution-trace`: lifecycle event payloads and independent status fields without changing event names.
- `desktop-client`: existing bilingual tool metadata and complete Simplified Chinese lifecycle labels with state-specific rendering.

## Impact

- Python Agent prompt assembly, runtime tool registration, and review-gate context projection.
- Trace/Gateway event payloads consumed by the React client.
- React timeline and generated-chart status presentation.
- Existing Python and frontend tests for Agent gates, lifecycle events, and labels.
- Archived tool-system and generated-chart-review changes remain authoritative for tool definitions and review algorithms.

