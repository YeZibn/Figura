# cli-gateway Specification

## Purpose

Provide a command-line entry for the ReAct `Agent`: an interactive shell that
registers the built-in tools and lets a user send lines that a tool-capable
agent loop turns into actions and final answers. The existing `Conversation`
chat REPL stays as the default interaction, with the agent shell selected
explicitly.

## Requirements

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

### Requirement: Chart-aware but freely planned agent behavior

The agent REPL SHALL use default guidance that identifies its chart-reading,
measurement, assembly, and validation capabilities. The guidance SHALL leave
the model free to decide whether to call tools, which tools to call, their
order, and whether the response should be natural language or structured data.

#### Scenario: Image question answered without a forced workflow

- **WHEN** a user asks a question about an attached image
- **THEN** the agent may answer directly or use any relevant tools according to
  the question, without infrastructure forcing a fixed tool sequence

#### Scenario: Plain non-chart request remains general-purpose

- **WHEN** a user submits a request unrelated to chart understanding
- **THEN** the agent remains able to answer or use its other registered tools,
  without requiring chart tools or ChartSpec output

### Requirement: Opt-in Agent trace mode

The Agent CLI SHALL provide an explicit trace mode that displays the Agent
execution trace while preserving the existing quiet output when trace mode is
not selected. Trace mode SHALL support human-readable output and a structured
JSON event format.

#### Scenario: Trace mode displays execution details

- **WHEN** the user starts the Agent REPL with trace mode enabled and submits a
  request that invokes tools
- **THEN** the CLI displays model turns, tool calls, tool results, visual
  observation summaries, and the final answer in execution order

#### Scenario: Default CLI remains quiet

- **WHEN** the user starts the Agent REPL without trace mode
- **THEN** the CLI continues to display the normal final answer without trace
  diagnostics

#### Scenario: JSON trace is machine-readable

- **WHEN** the user selects structured JSON trace output
- **THEN** the CLI emits one valid serialized trace event per record without
  raw image bytes or credentials

### Requirement: Explicit reasoning display option

The Agent CLI SHALL provide a separate explicit option for displaying
provider-returned reasoning in trace output. The option SHALL not alter whether
reasoning is retained in model history or sent back to the provider.

#### Scenario: Reasoning display is enabled

- **WHEN** the user enables the reasoning display option with trace mode
- **THEN** available provider-returned reasoning is shown with an explicit
  diagnostic label and bounded content

#### Scenario: Reasoning display is omitted

- **WHEN** trace mode is enabled without the reasoning display option
- **THEN** tool and execution events remain visible while provider reasoning
  is omitted
