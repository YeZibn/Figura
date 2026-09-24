## MODIFIED Requirements

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution
group with its status, duration or timestamps when available, event count, and
expand/collapse control. Inside the group it SHALL render ordered model,
tool, result, visual, and failure events, correlating tool evidence by call
identifier. A bounded or truncated tool result SHALL remain part of the
corresponding tool step and SHALL NOT become an unknown standalone step when
the outer tool identity is available.

#### Scenario: Completed run remains visible after reload

- **WHEN** the user reloads a session containing completed runs
- **THEN** the client restores their run summaries and can expand each one to
  inspect its persisted event history

#### Scenario: Tool status is correlated

- **WHEN** a tool call and its result share a call identifier
- **THEN** the UI shows one logical tool step whose status changes from running
  to success or failure
- **AND** its arguments, bounded result, and visual evidence are available
  behind the step disclosure control

#### Scenario: Truncated result remains in its tool step

- **WHEN** the Gateway marks a tool result body as truncated but preserves the
  originating tool name and call identifier
- **THEN** the UI keeps the result under the originating tool step
- **AND** it shows an explicit bounded or truncated-state indicator
- **AND** it does not render a separate “unknown tool” step

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was
  interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted
  state
- **AND** it does not fabricate missing execution steps
