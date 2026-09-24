## MODIFIED Requirements

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL preserve stable event kinds while carrying distinct
fields for tool execution status, candidate status, review status, and
publication status whenever applicable. `chart_review_started` SHALL mean that
the candidate-specific review obligation has started or is pending; it SHALL
not mean that review passed or that publication succeeded. Run lifecycle
events SHALL additionally distinguish active, completed, failed, and
interrupted states, and interruption reason SHALL remain separate from tool,
review, and publication outcomes.

#### Scenario: Tool result reports execution state only

- **WHEN** a tool call completes
- **THEN** its `tool_result` event reports the tool execution status
  independently of any candidate review or publication state
- **AND** a successful tool execution does not by itself produce a published
  status

#### Scenario: Review start has accurate semantics

- **WHEN** a generated candidate enters the review obligation
- **THEN** the trace emits `chart_review_started` with candidate and review
  references plus the independent candidate, review, and publication states
- **AND** the event does not present the candidate as verified or published

#### Scenario: Review completion records the publication outcome

- **WHEN** a review transition completes
- **THEN** the trace emits the review outcome and its independent publication
  status, including warning or rejection where applicable
- **AND** clients can distinguish review completion from publication success

#### Scenario: Interruption preserves independent outcomes

- **WHEN** an active run is interrupted while a tool, review, or publication
  operation is pending
- **THEN** the trace records the run interruption and bounded reason without
  rewriting the already-recorded tool or review outcome
- **AND** clients can distinguish interruption from review rejection or tool
  failure

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported lifecycle event, with the stable English event kind preserved
as the machine identifier. Unknown event kinds SHALL remain renderable using a
safe English fallback. Supported run terminal and interruption reason codes
SHALL also have bounded Simplified Chinese presentation labels.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains
  the original event kind for technical inspection

#### Scenario: Unknown lifecycle event remains visible

- **WHEN** a client receives an event kind absent from the label catalog
- **THEN** it displays the stable event kind as fallback text
- **AND** it does not discard or misclassify the event

#### Scenario: Interruption reason is localized

- **WHEN** a client renders a supported interruption reason
- **THEN** it displays its bounded Simplified Chinese label and retains the
  machine reason code for diagnostics

## ADDED Requirements

### Requirement: Run history has one cursor and terminal contract

The execution trace SHALL use one monotonic per-run event sequence for live
and persisted events. A history replay SHALL preserve sequence order, identify
retention gaps explicitly, and include or resolve to the authoritative run
terminal state. A terminal run SHALL not gain later client-visible execution
events.

#### Scenario: Replay resumes after a known sequence

- **WHEN** a client requests a run history after sequence 12
- **THEN** the returned events have greater sequences in ascending order and
  belong to the same run

#### Scenario: History gap is represented explicitly

- **WHEN** sequence 12 is no longer retained but later events remain
- **THEN** the trace returns a bounded history-gap indication
- **AND** it does not silently present the remaining events as complete

#### Scenario: Terminal event remains authoritative

- **WHEN** a terminal event has been recorded and a late producer reports
  progress
- **THEN** the late progress is not appended to the client-visible trace
- **AND** the original terminal event and reason remain authoritative

