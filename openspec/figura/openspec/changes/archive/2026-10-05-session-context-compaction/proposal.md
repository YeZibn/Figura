## Why

Figura currently sends complete Session history into later model requests, so long conversations can outgrow the configured model window even though local token estimation already exists. The Agent needs a source-linked summary for older closed interactions and a way to retrieve original messages, tool results, and images only when needed, while the durable Run facts remain complete and authoritative.

## What Changes

- Add threshold-triggered Session context compaction using an extra model request when a valid model context capacity is configured and estimated request occupancy reaches about 80%; target approximately 50% occupancy after compaction.
- Keep the newest interactions and the active Run's required context intact; summarize only older complete interaction boundaries and retain source references in the summary.
- When context capacity is unknown or the estimate is unavailable, do not automatically compact. Do not add a Run output budget, truncate durable history, or reject work based on the estimate.
- Add model-facing history search and source-reference read capabilities for conversation messages and committed tool results, plus typed image-resource reads for prior attachments, Panels, observations, and renders.
- Keep `RunState`, `RunExecutionState`, and their complete durable facts unchanged as sources of truth. Compact only the model request projection; retrieval returns original facts without re-running prior tools.
- Update Session history projection rules to allow a compact summary plus recent history and on-demand retrieval while preserving Session isolation, abnormal Run outcomes, and provider continuation compatibility.

## Capabilities

### New Capabilities
- `session-context-compaction`: Capacity-aware, source-linked compaction of model request context while retaining complete durable history.
- `session-context-retrieval`: Search and read prior Session messages, tool results, and authorized image resources by stable source reference.

### Modified Capabilities
- `session-memory`: Preserve complete canonical facts while allowing request-specific summary and recent-tail projections with source-linked retrieval.
- `local-context-token-estimation`: Allow the local estimate and configured capacity to trigger context compaction without turning estimation into admission, output, or Run limits.

## Impact

- Affected areas: `src/figura/memory/`, Agent prompt/request assembly and execution-state services, read-only history/resource tools and their registry, and Session/Run persistence for derived context summaries.
- Provider request preparation must distinguish the summarization request from ordinary Agent requests and preserve existing provider retry, continuation, and Run lifecycle invariants.
- Existing resource catalog semantics remain complete and read-only; only the prompt projection and new retrieval interfaces change.
- No new tokenizer, vector database, or second authoritative history store is introduced. Initial text search can be derived from canonical Run facts, with summaries providing semantic navigation.
