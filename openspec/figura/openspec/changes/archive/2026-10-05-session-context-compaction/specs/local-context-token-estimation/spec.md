## MODIFIED Requirements

### Requirement: Estimation does not control execution
The local estimate SHALL remain approximate display and compaction input data, not Provider-native accounting. When the selected Provider/model has a valid configured context capacity, request preparation MAY use the estimate to trigger context compaction according to the Session-context policy. The estimate SHALL NOT impose request admission, reserve output tokens, truncate canonical history, impose a Run output budget, automatically retry an ordinary Provider request, or stop a Run. Estimation failure SHALL produce absent estimation metadata while preserving otherwise valid execution and SHALL NOT trigger compaction. Provider-reported usage SHALL remain independently recorded and SHALL NOT replace or calibrate this local estimate.

#### Scenario: Estimator cannot initialize
- **WHEN** tokenizer resources cannot be loaded
- **THEN** an otherwise valid request continues without an estimate, without automatic compaction, and without exposing raw request content in diagnostics

#### Scenario: Estimate crosses configured capacity threshold
- **WHEN** a request estimate reaches the configured context-compaction threshold
- **THEN** request preparation may invoke the Session-context compaction behavior without treating the estimate as a hard admission limit

#### Scenario: Estimate exceeds configured capacity after best-effort compaction
- **WHEN** the compacted request estimate still exceeds configured capacity because required context cannot be removed safely
- **THEN** Figura preserves that context and follows existing Provider and payload behavior without truncating history or imposing a new Run budget

#### Scenario: Keep Provider usage independent
- **WHEN** a Provider returns native usage metadata
- **THEN** Figura records it independently and does not calibrate the shared local estimator from it
