# cli-gateway Specification

## Purpose

Provide a command-line entry for the ReAct `Agent`: an interactive shell that
registers the built-in tools and lets a user send lines that a tool-capable
agent loop turns into actions and final answers. The existing `Conversation`
chat REPL stays as the default interaction, with the agent shell selected
explicitly.

## ADDED Requirements

### Requirement: Tool-capable agent REPL entry

The system SHALL offer an interactive command-line shell that drives the
`Agent` ReAct loop with the built-in read-only tools registered, reading a line
at a time, printing each reply, and exiting on an empty line or Ctrl-D.

#### Scenario: Line becomes an agent run

- **WHEN** the user starts the agent shell and types a non-empty line
- **THEN** that line is passed to `Agent.run(...)` and the returned final text
  is printed

#### Scenario: Exit on empty line or Ctrl-D

- **WHEN** the user enters a blank line or triggers EOF/KeyboardInterrupt
- **THEN** the shell terminates and returns a zero exit code

### Requirement: Keep chat REPL as default, agent shell explicit

The system SHALL keep the existing `Conversation`-based chat REPL as the default
interaction, and SHALL expose the tool-capable agent shell only when explicitly
selected, so the two modes coexist without surprise.

#### Scenario: Default stays conversation chat

- **WHEN** the CLI runs without the agent flag
- **THEN** it uses the existing `Conversation` chat REPL as before

#### Scenario: Agent flag selects the agent shell

- **WHEN** the agent flag (e.g. `--agent`) is passed
- **THEN** the CLI runs the tool-capable agent REPL instead of the chat REPL

### Requirement: Reuses built-in tools without registry changes

The system SHALL wire the shell's agent with the built-in read-only tools via
`register_builtins`, without altering the `Agent` loop or the tool registry
semantics.

#### Scenario: Built-ins registered for the agent shell

- **WHEN** the agent shell starts an `Agent`
- **THEN** `register_builtins` has populated its `ToolRegistry` so the model may
  invoke `read_file`, `list_dir`, `parse_json`, and `read_json_file`