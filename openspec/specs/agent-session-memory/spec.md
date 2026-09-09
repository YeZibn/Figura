# agent-session-memory Specification

## Purpose

Provide resumable named Agent sessions and bounded model context while keeping the default interaction ephemeral and preserving valid tool-message groups.

## Requirements

### Requirement: Named Agent sessions are durable and opt-in

The system SHALL allow named sessions to restore completed runs after restart; without a named session, Agent history SHALL remain process-local.

#### Scenario: Named session resumes after restart

- **WHEN** a completed named session is opened again
- **THEN** its prior user, tool, and assistant information can enter bounded context

#### Scenario: Sessions are isolated

- **WHEN** two named sessions contain different histories
- **THEN** each exposes only records owned by that session

### Requirement: Agent runs have durable lifecycle states

Named runs SHALL persist ordered records with running, completed, failed, or interrupted states. Only completed runs SHALL enter later model context.

#### Scenario: Abandoned run is interrupted

- **WHEN** a session is reopened with an unfinished running run
- **THEN** that run becomes interrupted and its partial protocol is excluded

### Requirement: Model context is bounded by complete run blocks

Context SHALL contain the system prompt, bounded deterministic summaries, complete recent runs, and the current run. Assistant tool calls and matching tool results SHALL never be split.

#### Scenario: History exceeds the limit

- **WHEN** completed history exceeds the configured context limit
- **THEN** older completed runs are summarized deterministically without another model call

### Requirement: Durable memory excludes sensitive and binary content

Memory MUST exclude reasoning, credentials, raw provider responses, image bytes, data URLs, and unbounded tool content while retaining safe attachment references.

#### Scenario: Images are represented by references

- **WHEN** an image participates in a named run
- **THEN** only safe metadata and authorized references are persisted

### Requirement: Named sessions can be inspected and deleted

Users SHALL be able to list bounded session metadata and explicitly delete a session; deletion SHALL not modify referenced source files.

#### Scenario: Confirmed deletion

- **WHEN** the user confirms deletion
- **THEN** the session state and references are removed but source files remain
