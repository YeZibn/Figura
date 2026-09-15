# execution-trace Specification

## Purpose

Make Agent execution inspectable and recoverable across the live run, page reloads, session switches, and Gateway restarts while keeping final answers readable as safe Markdown.

## Requirements

### Requirement: Agent runs have durable execution history

The system SHALL preserve a bounded, ordered execution history for each Agent
run, including lifecycle events, model-turn boundaries, tool calls, tool
results, visual observations, failures, budget termination, and the final
answer when available. The history SHALL retain the event sequence and run
status independently from the model conversation history.

#### Scenario: Completed run history is available after reload

- **WHEN** an Agent run completes and the user reloads the desktop client
- **THEN** the client can retrieve the run's ordered execution history and
  final answer from the Gateway
- **AND** the recovered history contains the same bounded event order without
  requiring the Agent to run again

#### Scenario: Failed run history remains inspectable

- **WHEN** an Agent run fails after producing one or more execution events
- **THEN** the failure state and events produced before failure remain
  available for inspection
- **AND** the history does not claim a successful final answer

#### Scenario: Event history is bounded and sanitized

- **WHEN** an execution event contains oversized, sensitive, or binary data
- **THEN** the persisted and returned representation applies the existing
  trace limits and redaction rules
- **AND** it never exposes credentials, raw image bytes, data URLs, or local
  source paths

### Requirement: Live execution and historical execution use one ordered model

The system SHALL expose the same versioned event shape for live delivery and
historical retrieval. A client SHALL be able to combine an initial historical
replay with subsequent live events by sequence number without duplicating or
reordering events.

#### Scenario: New client hydrates before following a live run

- **WHEN** a client opens a run after events have already been emitted
- **THEN** it receives the available prior events in sequence order and then
  receives later events as they are emitted
- **AND** each event is rendered at most once

#### Scenario: Disconnected client resumes from a sequence

- **WHEN** the event connection is interrupted after sequence N and the run is
  still available
- **THEN** the client can request events after sequence N and receive every
  later available event in order
- **AND** the client keeps already-rendered events without replacing them

#### Scenario: Event history is no longer available

- **WHEN** a run or its bounded event history has expired or been removed
- **THEN** the client receives an explicit unavailable or history-gap state
- **AND** it does not silently show an incomplete execution as complete

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

### Requirement: Final answers are safe Markdown documents

The system SHALL preserve the final answer source text and allow the desktop
client to render it as safe Markdown. Rendering SHALL support ordinary
headings, paragraphs, emphasis, lists, tables, links, and fenced code blocks
without exposing unsanitized HTML or replacing the original answer text.

#### Scenario: Structured final answer is readable

- **WHEN** an Agent returns a Markdown answer containing headings, a table, and
  a code block
- **THEN** the desktop client renders those structures in the final answer
  area with the original content semantics preserved

#### Scenario: Malicious Markdown is bounded

- **WHEN** the final answer contains raw HTML, unsafe links, or oversized
  content
- **THEN** the client applies the configured safe rendering policy and size
  limits
- **AND** unsafe markup does not execute in the desktop client

### Requirement: Lifecycle events separate execution, review, and publication state

Lifecycle events SHALL preserve stable event kinds while carrying distinct
fields for tool execution status, candidate status, review status, and
publication status whenever applicable. `chart_review_started` SHALL mean that
the candidate-specific review obligation has started or is pending; it SHALL
not mean that review passed or that publication succeeded.

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

### Requirement: Lifecycle events have stable Chinese presentation labels

The execution protocol SHALL provide a bounded Simplified Chinese label for
each supported lifecycle event, with the stable English event kind preserved as
the machine identifier. Unknown event kinds SHALL remain renderable using a
safe English fallback.

#### Scenario: Known lifecycle event is localized

- **WHEN** a client renders a supported lifecycle event
- **THEN** it displays the corresponding Simplified Chinese label and retains
  the original event kind for technical inspection

#### Scenario: Unknown lifecycle event remains visible

- **WHEN** a client receives an event kind absent from the label catalog
- **THEN** it displays the stable event kind as fallback text
- **AND** it does not discard or misclassify the event

### Requirement: Execution history deletion follows session lifecycle

The system SHALL remove durable execution history and managed visual artifacts
when their owning session is deleted, subject to the same authorization and
cleanup guarantees as session records and attachments.

#### Scenario: Deleting a session removes its trace

- **WHEN** the user confirms deletion of an idle session
- **THEN** its runs, execution events, final answers, and managed visual trace
  artifacts are no longer readable through the Gateway
- **AND** another session's execution history is unaffected

### Requirement: Generated chart preview references follow candidate publication

Generated chart lifecycle events SHALL expose enough bounded identity and
status information for a client to resolve both an unpublished candidate and
its later published artifact. When a candidate is promoted, subsequent
historical or live representations SHALL provide a current artifact reference
or a stable preview resolution that does not depend on a stale candidate URL.

#### Scenario: Pending candidate has a preview resource

- **WHEN** a generated chart candidate is persisted for review
- **THEN** its event contains the candidate identity and the client can request
  the candidate image for an authorized owning run while it remains available

#### Scenario: Published artifact replaces a candidate

- **WHEN** a review promotes a candidate to a published or warning publication
  state
- **THEN** the resulting event and later history expose the published artifact
  identity and preview resource, and the client does not continue relying only
  on the old candidate resource

#### Scenario: Historical lifecycle can resolve the current image

- **WHEN** the client reloads a run after candidate publication or receives a
  lifecycle event out of order
- **THEN** it can resolve the current preview using the available bounded
  reference and displays an explicit pending or unavailable state when no
  current bytes can be served
