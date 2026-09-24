## ADDED Requirements

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
