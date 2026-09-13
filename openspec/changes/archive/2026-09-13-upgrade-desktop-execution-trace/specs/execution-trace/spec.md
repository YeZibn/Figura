## Purpose

Make Agent execution inspectable and recoverable across the live run, page reloads, session switches, and Gateway restarts while keeping final answers readable as safe Markdown.

## ADDED Requirements

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

The system SHALL preserve enough call and observation identifiers for clients
to associate a tool call with its result, error, and generated visual evidence.
The grouping SHALL retain intermediate evidence even when the final answer is
available.

#### Scenario: Tool call and result form one inspectable step

- **WHEN** a tool call emits a later result with the same call identifier
- **THEN** the client can render one step with running, success, or error state
  and expandable arguments and result details

#### Scenario: Visual evidence remains attached to its tool context

- **WHEN** a tool produces a visual observation for a call
- **THEN** the observation can be displayed inside or alongside that tool step
  with its caption and authorized resource reference
- **AND** the event history keeps the observation order relative to the call
  and result

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

### Requirement: Execution history deletion follows session lifecycle

The system SHALL remove durable execution history and managed visual artifacts
when their owning session is deleted, subject to the same authorization and
cleanup guarantees as session records and attachments.

#### Scenario: Deleting a session removes its trace

- **WHEN** the user confirms deletion of an idle session
- **THEN** its runs, execution events, final answers, and managed visual trace
  artifacts are no longer readable through the Gateway
- **AND** another session's execution history is unaffected
