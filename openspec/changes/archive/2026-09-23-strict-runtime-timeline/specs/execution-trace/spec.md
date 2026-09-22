## MODIFIED Requirements

### Requirement: Execution trace groups related tool evidence

The system SHALL preserve one canonical run identifier across Gateway run
acceptance, Agent execution, durable memory records, execution events,
conversation projection, attachments, visual observations, and generated chart
artifacts. Every measurement, generation, review, and publication event that
participates in the decision timeline SHALL contain a complete `unit_id`,
`unit_type`, `phase`, `actor`, `role`, and `transition_id`. A tool call and its
result SHALL use the same `unit_id` and `call_id`; a review cycle SHALL use one
canonical `review_id` for its candidate attempt. The producer SHALL reject a
timeline event that is missing required identity or state fields instead of
creating a legacy or unknown association.

The grouping SHALL retain intermediate evidence when the final answer is
available, while allowing generated chart artifacts to be displayed as final
Run results instead of duplicated as ordinary tool-step content.

Each tool-result event SHALL keep its bounded `tool_name`, `call_id`,
execution status, unit correlation, and turn/run correlation in the outer event
envelope even when the structured result body is truncated. Truncation SHALL
apply to the diagnostic result payload rather than replacing the identity
needed for client correlation.

#### Scenario: One canonical identity is used across a Run

- **WHEN** the Gateway accepts a message and starts an Agent run
- **THEN** the Run summary, durable Agent records, emitted events, projected messages, and managed artifacts identify that operation with the same canonical run identifier
- **AND** every timeline event has a complete semantic unit envelope

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client renders one step with running, success, or error state and expandable arguments and result details
- **AND** both events belong to the same canonical unit without tool-name or sequence guessing

#### Scenario: Missing timeline identity is rejected

- **WHEN** a producer attempts to persist a measurement, generation, review, or publication event without its required unit identity or state
- **THEN** the producer records a bounded protocol error and does not publish the malformed event to the user timeline
- **AND** the client does not synthesize a legacy, unknown, or orphan business step

#### Scenario: Oversized result preserves tool identity

- **WHEN** a tool result contains a trace, polyline, OCR collection, or other diagnostic payload larger than the event body limit
- **THEN** the event retains its bounded tool name, call identifier, unit identity, status, turn, and run correlation
- **AND** only the oversized result content is represented as truncated or summarized data

#### Scenario: Visual evidence remains attached to its tool context

- **WHEN** a tool produces a visual observation for a call
- **THEN** the observation can be displayed inside or alongside that tool step with its caption and authorized resource reference
- **AND** the event history keeps the observation order relative to the call and result under the same unit

#### Scenario: Generated chart remains available as Run output

- **WHEN** a Run produces a generated chart artifact
- **THEN** the artifact retains its canonical Run association, availability state, and authorized resource reference for the final result area
- **AND** the execution trace retains one bounded generation event without duplicating the artifact preview as a second tool step

#### Scenario: Expired generated chart is explicit

- **WHEN** a generated chart artifact is unavailable or expired when the Run is restored
- **THEN** the final result area shows its bounded unavailable state and preserves the surrounding Run structure
- **AND** the trace does not claim that the artifact preview is available

#### Scenario: Identity mismatch is explicit and recoverable

- **WHEN** restored data contains a Run summary and conversation records that cannot be associated with one canonical run identifier
- **THEN** the client preserves the records and shows an explicit incomplete or unavailable association state
- **AND** it does not silently present the mismatched records as one complete successful Run

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL keep tool execution, measurement observation, evidence
decision, canonical review, and publication status in independent fields.
`measurement_observed`, `measurement_evidence_selected`,
`measurement_evidence_discarded`, and `measurement_repair_exhausted` SHALL NOT
be interpreted as generated-chart review outcomes. `review_started` and
`review_completed` SHALL be the only public review lifecycle events for both
measurement and generated-chart review types; `chart_review_started` and
`chart_review_completed` SHALL NOT be emitted. Run lifecycle events SHALL
continue to distinguish active, completed, failed, interrupted, and history-gap
states.

#### Scenario: Tool result reports observation state only

- **WHEN** an OCR or chart measurement tool completes
- **THEN** `tool_result` and its observation events independently report execution status, scope, refs, quality warnings, and overlays
- **AND** tool success does not automatically produce accepted, published, or generated-review-passed state

#### Scenario: Evidence decision records model agency

- **WHEN** the main Agent selects, discards, or abandons an observation
- **THEN** the trace records the attempt, selected/discarded refs, semantic mapping, and decision source
- **AND** the original tool result remains traceable

#### Scenario: Generated review has one authoritative lifecycle

- **WHEN** a generated candidate enters review, repair, or publication
- **THEN** the trace contains one canonical `review_started` transition, one final `review_completed` or `review_failed` transition, and an explicit publication transition when applicable
- **AND** internal deterministic and VLM checks remain diagnostic details rather than parallel review lifecycles

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported user-facing lifecycle event, with the stable English event kind
preserved only as a machine identifier and technical detail. The user-facing
projection SHALL never use an unsupported event kind, `unknown`, or `legacy` as
visible fallback text. Unsupported or malformed event kinds SHALL remain
technical protocol errors and SHALL NOT create a business timeline item.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains the original event kind only for technical inspection

#### Scenario: Malformed lifecycle event is not shown as a business step

- **WHEN** a client receives an event that is absent from the supported event contract or lacks its required semantic envelope
- **THEN** it displays a bounded protocol or history error state
- **AND** it does not display the raw English kind as a completed user-facing step

#### Scenario: Interruption reason is localized

- **WHEN** a client renders a supported interruption reason
- **THEN** it displays its bounded Simplified Chinese label and retains the machine reason code for diagnostics
