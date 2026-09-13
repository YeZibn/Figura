## MODIFIED Requirements

### Requirement: Execution trace groups related tool evidence

The system SHALL preserve one canonical run identifier across Gateway run
acceptance, Agent execution, durable memory records, execution events,
conversation projection, attachments, visual observations, and generated
chart artifacts. It SHALL preserve enough call, observation, and artifact
identifiers for clients to associate a tool call with its result, error,
visual evidence, and generated chart output. The grouping SHALL retain
intermediate evidence when the final answer is available, while allowing
generated chart artifacts to be displayed as final Run results instead of
duplicated as ordinary tool-step content.

#### Scenario: One canonical identity is used across a Run

- **WHEN** the Gateway accepts a message and starts an Agent run
- **THEN** the Run summary, durable Agent records, emitted events, projected
  messages, and managed artifacts all identify that operation with the same
  canonical run identifier
- **AND** no second local Run identifier causes the conversation projection
  and execution history to describe separate runs

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client can render one step with running, success, or error state
  and expandable arguments and result details
- **AND** the step remains associated with its parent canonical Run

#### Scenario: Visual evidence remains attached to its tool context

- **WHEN** a tool produces a visual observation for a call
- **THEN** the observation can be displayed inside or alongside that tool step
  with its caption and authorized resource reference
- **AND** the event history keeps the observation order relative to the call
  and result under the same Run

#### Scenario: Generated chart remains available as Run output

- **WHEN** a Run produces a generated chart artifact
- **THEN** the artifact retains its canonical Run association, availability
  state, and authorized resource reference for the final result area
- **AND** the execution trace retains a bounded generation event without
  requiring the artifact preview to be duplicated inside the tool timeline

#### Scenario: Expired generated chart is explicit

- **WHEN** a generated chart artifact is unavailable or expired when the Run
  is restored
- **THEN** the final result area shows its bounded unavailable state and
  preserves the surrounding Run structure
- **AND** the trace does not claim that the artifact preview is available

#### Scenario: Identity mismatch is explicit and recoverable

- **WHEN** restored data contains a Run summary and conversation records that
  cannot be associated with one canonical run identifier
- **THEN** the client preserves the records and shows an explicit incomplete
  or unavailable association state
- **AND** it does not silently present the mismatched records as one complete
  successful Run
