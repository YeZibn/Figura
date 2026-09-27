## MODIFIED Requirements

### Requirement: Tool-call intents are committed with their model response
Figura SHALL persist tool-execution facts in a per-Run monotonically increasing sequence separate from the core record sequence. It SHALL persist a normalized model response and all associated tool-call intents as one atomic Run progress transition. A response containing tool calls SHALL use the `tool_calls` finish reason. If the response contains provider-private continuation, that continuation SHALL be valid, provider-scoped, within its durable resource bound, and atomically linked to the same model response. Tool-call intents SHALL retain the response reference, opaque call ID, tool name, raw bounded JSON arguments, provider order, and the tool registry version used to produce the call. One response SHALL contain no more than 64 calls, each argument SHALL be no larger than 64 KiB UTF-8, and aggregate argument bytes SHALL not exceed 1 MiB. Call IDs SHALL be unique within the Run and positions SHALL be contiguous starting at zero.

#### Scenario: Commit a bounded tool-call batch
- **WHEN** a current model action receives a valid response with one or more bounded tool calls, absent or valid provider-private continuation, and the expected checkpoint revision
- **THEN** Figura persists the response, optional continuation, and all ordered call intents together and advances the checkpoint to the first call

#### Scenario: Reject an invalid or oversized batch or continuation
- **WHEN** a response has duplicate call IDs, invalid positions, more than 64 calls, an argument over 64 KiB, aggregate arguments over 1 MiB, or a continuation that is invalid, mismatched, unsupported, or oversized
- **THEN** Figura rejects the response without adding any response, continuation, tool-call, checkpoint, or event facts
