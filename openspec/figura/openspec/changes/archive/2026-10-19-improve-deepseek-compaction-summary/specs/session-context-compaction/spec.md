## ADDED Requirements

### Requirement: DeepSeek compaction requests use isolated medium reasoning
When Figura creates a context-compaction summary request for DeepSeek, it SHALL explicitly enable thinking and set `reasoning_effort` to `medium`. These options SHALL be part of the frozen Provider request descriptor so retries and recovery reuse the same request identity. This override SHALL apply only to compaction requests; ordinary Agent requests SHALL retain their configured reasoning options. Summary requests for other Providers SHALL retain their existing option-resolution behavior.

#### Scenario: Bind medium reasoning for a new DeepSeek summary request
- **WHEN** Figura creates a new compaction summary request for DeepSeek
- **THEN** the prepared request enables thinking, uses medium reasoning effort, and freezes both values in its request descriptor

#### Scenario: Leave ordinary DeepSeek requests unchanged
- **WHEN** Figura prepares an ordinary Agent request for DeepSeek
- **THEN** it uses the configured ordinary-request reasoning options rather than the compaction override

#### Scenario: Preserve other Provider summary settings
- **WHEN** Figura creates a compaction summary request for a Provider other than DeepSeek
- **THEN** it uses that Provider's existing option-resolution behavior without applying DeepSeek's medium-reasoning override

#### Scenario: Retry with the bound reasoning options
- **WHEN** a DeepSeek summary request is retried or resumed after its request descriptor has been frozen
- **THEN** Figura reuses the frozen medium-reasoning options and does not derive new options from a changed Provider profile

### Requirement: DeepSeek summary validation uses final assistant content
Figura SHALL allow a DeepSeek summary response to contain a provider-private reasoning continuation when the response otherwise satisfies the summary response envelope. It SHALL parse and validate only the final assistant content against the existing JSON, field, and authorized-source-reference contract. The continuation SHALL NOT be copied into the installed summary checkpoint or ordinary Agent history. Providers other than DeepSeek SHALL retain the existing summary response contract.

#### Scenario: Accept a valid DeepSeek summary with a reasoning continuation
- **WHEN** DeepSeek returns a stopped text response with valid summary JSON and a reasoning continuation
- **THEN** Figura validates the final assistant content and may install the source-validated summary without including the continuation

#### Scenario: Reject invalid final content despite a continuation
- **WHEN** a DeepSeek response contains a reasoning continuation but its final assistant content is missing or violates the summary JSON or source-reference contract
- **THEN** Figura rejects the summary, preserves the prior checkpoint, and follows the existing safe fallback behavior

#### Scenario: Keep the non-DeepSeek response contract
- **WHEN** another Provider returns a summary response containing a continuation
- **THEN** Figura applies the existing response validation behavior for that Provider

### Requirement: Existing frozen summary requests are not silently rebound
When recovery finds an unfinished compaction operation whose frozen DeepSeek summary options do not satisfy the current medium-reasoning policy, Figura SHALL NOT rewrite the descriptor or dispatch a request with changed options under the same operation identity. It SHALL resolve the operation through the existing safe fallback behavior while preserving any prior valid checkpoint.

#### Scenario: Fall back from an unfinished operation with old reasoning options
- **WHEN** recovery encounters an unfinished DeepSeek compaction operation bound to reasoning options other than enabled thinking with medium effort
- **THEN** Figura does not mutate or dispatch that operation and continues through the existing safe fallback path with the prior checkpoint unchanged
