## ADDED Requirements

### Requirement: Composer displays approximate recent request occupancy
Figura mode SHALL display a compact context indicator near the composer from the active Run summary, or the most recent Run when no Run is active. With a known capacity it SHALL display approximate percentage computed as `inputTokens / contextWindowTokens * 100`, with detail showing counts and explaining that they belong to the most recent model request. Unknown capacity SHALL show only estimated token count; absent metadata SHALL show an unestimated state. The indicator SHALL NOT accumulate Run usage, track unsent drafts or streaming output, or rebase a previous request onto a newly selected Provider. Values above 100 percent SHALL remain visible numerically while any visual fill is capped at 100 percent, without preventing submission.

#### Scenario: Show the latest input estimate
- **WHEN** consecutive logical requests have estimates of 20,000, 25,000 and 30,000 tokens
- **THEN** the indicator uses 30,000 tokens rather than their sum

#### Scenario: Change the next request Provider
- **WHEN** the user selects another Provider before submitting a new Run
- **THEN** any existing indicator retains its originating Run model and capacity, identified in its detail, instead of using the newly selected capacity

#### Scenario: Start a Run without an estimate
- **WHEN** a new active Run has not yet bound its first request
- **THEN** the indicator shows an unestimated state without reusing the previous Run estimate

### Requirement: Context display follows existing client lifecycle ownership
The optional context metadata SHALL pass through the existing Figura client and workspace compatibility layers. Components SHALL obtain it through existing Run state and SHALL NOT introduce direct Gateway calls, duplicate event merging or independent reconnect ownership. Older DTOs and other client modes lacking this field SHALL remain functional.

#### Scenario: Reconnect and reload
- **WHEN** existing Run-history compensation receives an updated Run summary
- **THEN** the context indicator converges through the same lifecycle owner as other Run state

#### Scenario: Read an older DTO
- **WHEN** the client receives a Run summary without `contextUsage`
- **THEN** it renders normally without requiring the new field or changing other client modes
