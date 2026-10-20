## ADDED Requirements

### Requirement: Transient Provider deltas never become canonical Run history
Figura SHALL render transient assistant text deltas only for the active Provider attempt identified by the Gateway. On a new attempt, reconnect, terminal response, or Run reload, the client SHALL discard any incomplete transient buffer and converge on the canonical Session and Run projection. It SHALL NOT display Provider reasoning or partial tool-call arguments as assistant text. Durable Run lifecycle cursor ownership and event merging SHALL remain in the shared run lifecycle controller.

#### Scenario: Render an active assistant response
- **WHEN** the active Run receives ordered deltas for its current Provider attempt
- **THEN** the conversation view displays the assistant text as provisional content without inserting it into durable Session history

#### Scenario: Replace partial text after a retry
- **WHEN** the Gateway announces a new Provider attempt after a previous stream interruption
- **THEN** the client clears the old attempt's provisional text before rendering deltas from the new attempt

#### Scenario: Reconnect during a stream
- **WHEN** the browser reconnects after missing transient deltas
- **THEN** the client preserves the durable event cursor, discards incomplete provisional text, and continues to display the Run's durable state until a complete response is committed

#### Scenario: Converge after completion
- **WHEN** a complete Provider response is committed and a terminal or progress event triggers Session refresh
- **THEN** the client replaces provisional text with the canonical committed response exactly once

#### Scenario: Keep private or incomplete content hidden
- **WHEN** Provider events contain reasoning or incomplete tool-call fragments
- **THEN** the client receives no such content as assistant text and renders no provisional tool result
