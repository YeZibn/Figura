## Purpose

Provides a multi-turn conversation session that owns its message history in
memory, drives each turn through the LLM client, and exposes an in-memory
channel for interactive use, as the interaction layer above the LLM client and
a base for future tool/agent loops.

## ADDED Requirements

### Requirement: Multi-turn conversation session

The system SHALL provide a stateful conversation session that holds its message
history in memory. Each turn SHALL append the user's input, obtain a reply via
the LLM client, and append the assistant's reply to the same history so that
later turns are sent with full prior context.

#### Scenario: Successive turns accumulate context

- **WHEN** a caller submits several user messages across multiple turns
- **THEN** each turn's user message and assistant reply accumulate in the
  in-memory history, and every subsequent call is made with the full history so
  far

### Requirement: Assistant history excludes reasoning

When the underlying LLM client returns separate reasoning output, the session
SHALL persist only the assistant's content in history (never the reasoning), so
deep-thinking providers are not given reasoning back. The reply content
returned to the caller SHALL include the assistant's content.

#### Scenario: Deep-thinking turn keeps history clean

- **WHEN** a turn's reply contains reasoning produced by a deep-thinking model
- **THEN** the history entry for that assistant reply contains only content, the
  returned reply exposes the content, and the reasoning is not injected back into
  any later turn

### Requirement: Configurable system prompt and default model

The session SHALL accept an optional system prompt and an optional default model
at creation. The system prompt, when provided, SHALL be the first entry of the
history and persist across turns; the default model SHALL be used for turns that
do not specify one.

#### Scenario: System prompt present at start of every turn

- **WHEN** a session is created with a system prompt and turns are run
- **THEN** the system prompt is the first message in history and remains part of
  every call

### Requirement: Session reset and history access

The session SHALL support resetting its history (back to the initial system
prompt, if any) and SHALL expose its in-memory history read-only so callers can
inspect or debug it.

#### Scenario: Reset clears conversation history

- **WHEN** a caller resets a session after several turns
- **THEN** the history is cleared back to its initial system prompt and a new
  conversation can start without prior turns

### Requirement: Interactive command-line loop

The system SHALL provide a command-line entry point that presents a prompt,
reads user input repeatedly, sends each input to a conversation session, prints
the reply, and continues until the user exits. Termination by the user SHALL NOT
persist the session anywhere (memory-only).

#### Scenario: Repeated interactive turns until exit

- **WHEN** a user runs the command-line loop and types several inputs and then
  exits
- **THEN** each input is answered from the conversation context, the loop keeps
  running until exit, and no history is persisted to disk