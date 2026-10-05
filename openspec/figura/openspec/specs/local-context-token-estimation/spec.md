# local-context-token-estimation Specification

## Purpose

为 Figura 的实际模型输入提供跨 Provider 一致的本地 token 近似计量，使用户能够理解最近一次请求的上下文占用。该能力只提供展示数据，保持执行、工具调用、历史与重试行为独立于估算结果。

## Requirements

### Requirement: Local estimation covers actual model input uniformly
Figura SHALL apply one versioned local text-counting rule to every supported Provider. It SHALL estimate the actual prepared model input, including ordered messages, instructions, tool definitions, tool-call names and IDs, arguments, results, and continuation content only when actually replayed. It SHALL exclude transport settings, credentials, endpoints, generation controls, resources not sent, and historical cumulative usage. Special-token-like user text SHALL be counted as ordinary text. The estimate SHALL be identified as approximate rather than native Provider accounting.

#### Scenario: Count a complete tool-enabled request
- **WHEN** a prepared request contains instructions, history, tool schemas, tool calls, results and replayed continuation
- **THEN** the estimate includes all those input components under the same counting rule without persisting their content in estimation metadata

#### Scenario: Exclude unrelated resource inventory
- **WHEN** an attachment is stored but its content is not sent in the request
- **THEN** its image or text content is not counted, while any metadata actually present in the request is counted

#### Scenario: Preserve ordinary special-token-like text
- **WHEN** user text or a tool result contains strings resembling tokenizer special tokens
- **THEN** estimation counts them as ordinary content without rejecting the model request

### Requirement: Images have one explicit approximate cost
Figura SHALL exclude image URLs and base64 image bodies from text counting and SHALL add 1,024 estimated tokens for each image occurrence actually included in the request. This rule SHALL be identical across Providers and SHALL NOT be described as native visual token accounting. Changing the counting rule SHALL change the estimator version.

#### Scenario: Count repeated image occurrences
- **WHEN** the request includes two image blocks, including two occurrences of the same image
- **THEN** it adds 2,048 image tokens without text-tokenizing either image body or URL

### Requirement: Context capacity is optional display metadata
Figura SHALL support an optional positive integer context capacity for each configured Provider/model. Missing or invalid capacity SHALL produce an unknown display denominator without making the Provider unavailable. Capacity SHALL NOT enforce admission, reserve output tokens or impose Run budgets.

#### Scenario: Capacity is unknown
- **WHEN** a model has no valid configured capacity
- **THEN** its local input estimate remains available and no percentage is invented

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
