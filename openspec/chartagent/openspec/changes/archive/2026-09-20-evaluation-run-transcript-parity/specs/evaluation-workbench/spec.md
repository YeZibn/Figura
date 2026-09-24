## MODIFIED Requirements

### Requirement: User can inspect an evaluation and its cases

The Gateway SHALL expose read-only detail resources for a selected evaluation and case. A detail response SHALL include the evaluation metadata, case status, session/run references, expected sample metadata, stage timeline, first confirmed failure, bounded summary/diagnostic references, and available report metadata. The response SHALL preserve `not_reached`, `not_observed`, `failed`, and partial states instead of presenting an incomplete run as successful.

#### Scenario: User selects a completed or partial evaluation

- **WHEN** the client requests a valid evaluation detail
- **THEN** the Gateway returns the batch metadata and all available case summaries without requiring the caller to open the evaluation's SQLite database

#### Scenario: User selects one case

- **WHEN** the client requests a valid case belonging to an evaluation
- **THEN** the Gateway returns its run reference, ordered stage states, bounded error summary, report references, and available evidence references
- **AND** an unknown evaluation or case returns a bounded not-found response

#### Scenario: Case history is requested

- **WHEN** the client requests the ordered history for a case with a persisted run
- **THEN** the Gateway returns the same safe run-event envelope and payload semantics used by an ordinary session run, including lifecycle events, tool calls, tool results, visual observations, repair/review events, failures, and recovery events
- **AND** each event preserves its sequence, timestamp, status, and `call_id` when available
- **AND** visual evidence uses stable evaluation-scoped resource references
- **AND** the response does not return the underlying `sessions.db` or local filesystem paths

### Requirement: User can expand bounded read-only run details

The evaluation workspace SHALL provide a read-only run transcript whose grouping and presentation semantics match the ordinary session execution timeline. It SHALL display the complete available sanitized values for user/model-visible messages, tool calls, tool results, measurement-repair details, review state, lifecycle events, errors, recovery state, and evaluation-scoped visual evidence. Safety bounds MAY limit transport size or conceal sensitive content, but a complete persisted result SHALL NOT be replaced by a summary solely because its structured value is deeply nested.

#### Scenario: User expands a tool call and result

- **WHEN** the user expands a tool call or tool result in a selected case's run transcript
- **THEN** the client displays the tool name, call identifier, sanitized arguments, sanitized structured result, status, sequence, timestamp, and related visual evidence using the same grouping semantics as an ordinary session run
- **AND** the user can distinguish the invocation from the returned result without seeing duplicate competing representations of the same tool result

#### Scenario: User expands conversation content

- **WHEN** a case has persisted user or model-visible conversation records
- **THEN** the client displays those records in chronological relation to the execution transcript
- **AND** missing or truncated conversation records do not hide the available Gateway event transcript or case diagnosis

#### Scenario: Deeply nested chart data is displayed

- **WHEN** a tool result contains nested chart geometry such as bounding boxes, polygons, axes, bars, series, or point coordinates
- **THEN** the client preserves the numeric and structural values available in the persisted safe result
- **AND** the Gateway does not mark those values truncated solely because they exceed a global recursion-depth threshold

#### Scenario: Detail data is truncated or unavailable

- **WHEN** a result was truncated during persistence, exceeds the configured transport limit, or is unavailable in the bundle
- **THEN** the client displays an explicit source and reason such as persistence truncation, detail-resource unavailable, or history gap
- **AND** the client preserves all remaining transcript entries without fabricating missing content or exposing an arbitrary local file as a fallback

#### Scenario: Detailed content crosses a sensitive-data boundary

- **WHEN** an expanded record contains credentials, absolute local paths, hidden reasoning, raw binary data, or unbounded provider payload fields
- **THEN** the Gateway redacts, omits, or replaces those fields with bounded markers before returning the detail
- **AND** the client continues to use evaluation-scoped resource references for images

### Requirement: Evaluation run transcript matches ordinary session trace

The evaluation workspace SHALL render a selected case as a read-only equivalent of the ordinary session run trace. It SHALL use the same event labels, tool-call/result correlation, expandable result behavior, visual-observation attachment behavior, and lifecycle/error presentation, while preserving evaluation-specific case, report, and evidence context.

#### Scenario: User reviews a selected case like a normal conversation run

- **WHEN** the user opens a case with a persisted run
- **THEN** the evaluation workspace shows the run transcript without requiring a separate summary-only timeline before tool details can be inspected
- **AND** tool calls, tool results, observations, repair events, review events, and terminal events appear in their original execution order

#### Scenario: Evaluation transcript remains read-only

- **WHEN** the user expands or refreshes an evaluation transcript
- **THEN** the client never submits a new model/tool operation or mutates the evaluation bundle
- **AND** the ordinary session workspace retains its existing run, retry, resume, and interruption behavior

## ADDED Requirements

### Requirement: Large sanitized tool results remain retrievable

The evaluation system SHALL support on-demand retrieval of a complete sanitized tool result when the result cannot fit in the ordinary event envelope. The detail resource SHALL be evaluation- and case-scoped, allowlisted, bounded, and independent from raw SQLite or provider payload access. Existing bundles without such a resource SHALL remain readable through their persisted event result and SHALL report unrecoverable truncation explicitly.

#### Scenario: Large result has a detail resource

- **WHEN** a sanitized tool result exceeds the ordinary event envelope but a registered evaluation detail resource exists
- **THEN** the history event retains its identity, `call_id`, status, sequence, and a detail-resource reference
- **AND** expanding the tool result loads and displays the complete sanitized structured result on demand

#### Scenario: Large result was truncated before a detail resource existed

- **WHEN** a historical result was already truncated during persistence and no complete detail resource is registered
- **THEN** the client displays the persisted preview and an explicit unrecoverable-truncation marker
- **AND** the system does not infer or fabricate the missing fields

#### Scenario: Detail resource is unauthorized or unavailable

- **WHEN** a detail-resource request crosses evaluation/case ownership, points to a missing file, exceeds its resource limit, or uses an unsupported media type
- **THEN** the Gateway returns a bounded unavailable/not-found error
- **AND** the transcript keeps the event identity and shows the remaining run history
