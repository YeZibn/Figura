## Why

Figura durably stores ordered tool calls, attempts, and results, but the web workspace currently shows only Run lifecycle events and the final answer, with Panels and rendered charts in separate galleries. The shared frontend already has a concise tool-timeline presentation for legacy ChartAgent events; Figura needs a projection over its own durable facts so users can understand how a Run reached its result.

## What Changes

- Project each Figura Run's committed tool facts as an ordered user-facing timeline, grouping a call, its attempts, and its result into one logical step. Load bounded details only when a user expands a step.
- Add a durable `run_progress` stream marker when tool calls, attempts, or results commit. The marker carries only the new checkpoint revision; timeline content remains derived from the authoritative facts.
- Let the Figura Gateway return timeline snapshots and authorized observation-image content derived from committed facts and existing image sources. Do not persist duplicate timeline records or reconstructed annotation images.
- Render the timeline in Figura mode with the existing flat, collapsed-by-default interaction. Keep Panel and rendered-chart galleries as separate Run outputs; leave model selection, tool selection, and observation-scope decisions with the Agent.
- Preserve ChartAgent and mock behavior, Run event identity, and the rule that unknown or unresolved outcomes are never shown as success.

## Capabilities

### New Capabilities

<!-- No new standalone capability; this extends the existing Runtime, Gateway, and React contracts. -->

### Modified Capabilities

- `run-execution-core`: emit replayable progress markers atomically with durable tool-fact transitions without copying tool payloads into the event stream.
- `figura-web-gateway`: expose bounded per-Run timeline snapshots/details and authorized observation-image reads; stream progress markers for refresh.
- `figura-web-client`: display chronological Figura tool steps, their safe summaries and on-demand details, while retaining separate Panel and render galleries.

## Impact

- Runtime event kinds and SQLite write transactions for model responses containing tool calls, tool-attempt starts, and tool-result commits.
- Figura Gateway run-history/SSE projection and new Session-scoped Run timeline/detail/image reads.
- Figura API DTOs, adapter, run lifecycle refresh, timeline presentation, and frontend smoke coverage. No ChartAgent event schema or adapter changes.
