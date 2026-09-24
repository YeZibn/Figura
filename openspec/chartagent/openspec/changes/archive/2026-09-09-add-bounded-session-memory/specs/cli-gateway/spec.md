## ADDED Requirements

### Requirement: Agent CLI manages opt-in named sessions

The Agent CLI SHALL support explicit operations to create or resume a named
session, create a fresh session without overwriting an existing name, list
session metadata, and delete a named session after confirmation. Session
options SHALL apply only to the Agent mode, and omitting them SHALL preserve the
existing ephemeral Agent behavior.

#### Scenario: Session name resumes or creates

- **WHEN** the user starts Agent mode with `--session <name>`
- **THEN** the CLI resumes that named session when it exists or creates it when
  it does not

#### Scenario: New session refuses overwrite

- **WHEN** the user requests `--new-session <name>` and that name already exists
- **THEN** the CLI reports a bounded error without modifying the existing session

#### Scenario: Sessions can be listed without starting the REPL

- **WHEN** the user selects the session-listing operation
- **THEN** the CLI prints bounded session metadata and exits without invoking
  the model

#### Scenario: Session deletion requires confirmation

- **WHEN** the user requests deletion of a named session
- **THEN** the CLI asks for confirmation before deleting session state and does
  not delete referenced source files

#### Scenario: Session options require Agent mode

- **WHEN** a session-management option is supplied without Agent mode
- **THEN** the CLI rejects the malformed combination without starting either REPL

### Requirement: Agent CLI registers attachment-loading capability

The Agent CLI SHALL register `load_image` alongside the existing built-in and
chart tools, and SHALL describe registered attachment IDs to the model without
including arbitrary paths or eager image data.

#### Scenario: Agent REPL exposes load_image

- **WHEN** the Agent REPL starts
- **THEN** its tool registry contains `load_image` bound to the active ephemeral
  or named session's attachment registry

