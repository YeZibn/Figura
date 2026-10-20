## Why

DeepSeek compaction requests currently inherit the Provider's general reasoning configuration. A recent real run returned a valid structured summary together with a private reasoning continuation, but summary validation rejected the response before parsing its final answer. This prevents compaction from completing and makes the context-comparison experiment inconclusive.

## What Changes

- Give DeepSeek compaction requests their own frozen Provider options: thinking enabled with medium reasoning effort. Leave ordinary Agent requests and other Providers' settings unchanged.
- Accept a DeepSeek reasoning continuation in the summary response envelope while validating only the final assistant content against the existing JSON and source-reference contract.
- Keep reasoning continuation out of the installed summary checkpoint and ordinary Agent history. Invalid or incomplete final answers continue to use the existing safe fallback behavior.
- Preserve the immutable request binding of in-progress operations. An unfinished operation bound to different reasoning options must fall back safely rather than silently changing its request identity.
- Make the paired context experiment capacity-safe and compare Provider input tokens only for the same fact questions answered correctly by both arms, counting shared summary generation once.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-context-compaction`: define DeepSeek-specific summary reasoning options and response validation while preserving the existing compaction boundaries and fallback contract.

## Impact

The change affects summary-request construction in `src/figura/agent/request.py`, Provider request binding and DeepSeek payload handling, summary response validation and checkpoint installation, and focused provider/compaction tests. It does not change ordinary Agent reasoning settings, other Providers, configured context capacity, compaction budgets, summary prompt target, or canonical Run history.
