## ADDED Requirements

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL preserve stable event kinds while carrying distinct
fields for tool execution status, candidate status, review status, and
publication status whenever applicable. `chart_review_started` SHALL mean that
the candidate-specific review obligation has started or is pending; it SHALL
not mean that review passed or that publication succeeded.

#### Scenario: Tool result reports execution state only

- **WHEN** a tool call completes
- **THEN** its `tool_result` event reports the tool execution status independently of any candidate review or publication state
- **AND** a successful tool execution does not by itself produce a published status

#### Scenario: Review start has accurate semantics

- **WHEN** a generated candidate enters the review obligation
- **THEN** the trace emits `chart_review_started` with candidate and review references plus the independent candidate, review, and publication states
- **AND** the event does not present the candidate as verified or published

#### Scenario: Review completion records the publication outcome

- **WHEN** a review transition completes
- **THEN** the trace emits the review outcome and its independent publication status, including warning or rejection where applicable
- **AND** clients can distinguish review completion from publication success

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported lifecycle event, with the stable English event kind preserved as
the machine identifier. Unknown event kinds SHALL remain renderable using a
safe English fallback.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains the original event kind for technical inspection

#### Scenario: Unknown lifecycle event remains visible

- **WHEN** a client receives an event kind absent from the label catalog
- **THEN** it displays the stable event kind as fallback text
- **AND** it does not discard or misclassify the event

