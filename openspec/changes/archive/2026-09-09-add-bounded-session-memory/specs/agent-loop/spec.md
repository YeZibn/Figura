## MODIFIED Requirements

### Requirement: Agent owns its message history in memory

The system SHALL manage Agent history through a session-memory boundary. The
default implementation SHALL retain the running history only in memory, while
an explicitly selected named session MAY durably restore completed prior runs.
In both modes, the Agent SHALL send only the valid bounded context produced by
that memory boundary and SHALL allow reset or a new session to start without
prior conversational context.

#### Scenario: History accumulates across steps

- **WHEN** an agent run performs multiple tool-calling steps
- **THEN** assistant turns with their tool calls and tool observations are
  retained in order so the model sees its prior actions within bounded context

#### Scenario: Reset starts a new history

- **WHEN** the agent is reset or built with a fresh ephemeral memory
- **THEN** its active context restarts from the system prompt and later runs no
  longer receive prior messages

#### Scenario: Named memory supplies bounded prior context

- **WHEN** an Agent is connected to a resumed named session
- **THEN** it receives valid bounded context from completed runs without taking
  direct responsibility for database storage or binary attachment persistence

