## Purpose

Provide resumable named Agent sessions and bounded model context while keeping
the default interaction ephemeral and preserving valid tool-message groups.

## ADDED Requirements

### Requirement: Named Agent sessions are durable and opt-in

The system SHALL allow callers to create or resume a named Agent session whose
completed runs remain available after the process exits. An Agent started
without a named session SHALL retain the existing memory-only behavior and
SHALL NOT persist its conversation.

#### Scenario: Named session resumes after restart

- **WHEN** a user completes one or more Agent runs in a named session, exits,
  and later opens the same session name
- **THEN** the Agent reconstructs context from that session's stored completed
  runs and can use their prior user, tool, and assistant information

#### Scenario: Default Agent remains ephemeral

- **WHEN** a user starts the Agent without selecting a named session
- **THEN** the Agent stores history only for that process and leaves no durable
  session records after exit

#### Scenario: Sessions are isolated

- **WHEN** two named sessions contain different histories
- **THEN** opening either session exposes only records owned by that session

### Requirement: Agent runs have durable lifecycle states

The system SHALL record each named-session Agent run with an ordered sequence
of records and a lifecycle state of running, completed, failed, or interrupted.
Only completed runs SHALL be eligible for later model context.

#### Scenario: Successful run becomes available to later turns

- **WHEN** an Agent run reaches a final answer or its bounded budget outcome
- **THEN** the run is marked completed and its valid ordered records may be used
  in subsequent context

#### Scenario: Provider failure does not create invalid context

- **WHEN** a provider or process failure leaves a run without a valid terminal
  outcome
- **THEN** the run is marked failed or interrupted and its partial protocol
  messages are excluded from future model requests

#### Scenario: Restart resolves abandoned running state

- **WHEN** a named session is reopened with a previously running run that was
  not completed
- **THEN** the abandoned run is classified as interrupted before new work begins

### Requirement: Model context is bounded by complete run blocks

The system SHALL construct each model request from the system prompt, a bounded
deterministic summary of older completed runs, the most recent complete runs
that fit the configured context limit, and the current run. It MUST treat an
assistant tool-call message and all corresponding tool results as an indivisible
protocol block.

#### Scenario: Old runs are compacted deterministically

- **WHEN** completed history exceeds the configured context limit
- **THEN** older runs are represented by a bounded deterministic summary and no
  additional model call is made to create that summary

#### Scenario: Tool protocol group is never split

- **WHEN** the context boundary falls inside a run containing assistant tool
  calls, tool results, and a visual observation
- **THEN** the complete protocol group is either retained or omitted as a unit
  so the provider never receives an unmatched tool call or result

#### Scenario: Stored transcript remains more complete than model context

- **WHEN** old runs are omitted or summarized for a model request
- **THEN** their bounded durable records remain available for session inspection
  until the user explicitly deletes the session

### Requirement: Durable memory excludes sensitive and binary content

The system MUST NOT persist provider reasoning, credentials, authorization
material, raw provider responses, image base64, source-image bytes, or
generated-image bytes. Persisted text and structured tool content SHALL be
bounded and sanitized before storage.

#### Scenario: Reasoning is not stored

- **WHEN** a provider returns reasoning during a named-session run
- **THEN** that reasoning may be shown through the explicit trace path but is
  absent from all durable session records

#### Scenario: Images are represented by references

- **WHEN** a user attachment or generated visual observation participates in a
  named-session run
- **THEN** durable memory contains only safe metadata and authorized references,
  not the image payload or a base64 data URL

### Requirement: Named sessions can be inspected and deleted

The system SHALL allow users to list named sessions and explicitly delete one
session's durable records. Deleting a session MUST NOT delete or modify any
source image referenced by that session.

#### Scenario: Session listing is metadata-only

- **WHEN** a user lists named sessions
- **THEN** the result shows bounded identifying metadata such as name and update
  time without printing full transcripts or attachment contents

#### Scenario: Confirmed deletion removes only session state

- **WHEN** a user confirms deletion of a named session
- **THEN** its stored runs and attachment references are removed while referenced
  local files remain unchanged

