## ADDED Requirements

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
- **THEN** tool and execution events remain visible while provider reasoning is
  omitted
