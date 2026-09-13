## MODIFIED Requirements

### Requirement: User can inspect a conversation

The conversation area SHALL render user messages, Agent answers, and each
completed or active run as distinct chronological items. Final Agent answers
SHALL be rendered as safe Markdown, while execution details SHALL be grouped
under an expandable run summary and SHALL remain available after the answer is
shown.

#### Scenario: Conversation renders mixed content

- **WHEN** a session contains user messages, assistant answers, runs, tool
  steps, and visual observations
- **THEN** the UI renders them in chronological order with role-appropriate
  labels and content presentation
- **AND** tool calls and results can be associated within their run context

#### Scenario: Execution details are collapsed by default

- **WHEN** a conversation contains completed execution details
- **THEN** the primary answer remains easy to scan and the run details are
  represented by a compact expandable summary
- **AND** opening or closing the summary does not change message order or lose
  any event

#### Scenario: User enters a message

- **WHEN** the user enters non-empty text and activates send
- **THEN** the UI adds a user message and shows a pending/loading state for the
  assistant response
- **AND** the new run gets a persistent execution container as soon as its ID
  is available

#### Scenario: Final answer renders Markdown

- **WHEN** the Agent answer contains Markdown headings, lists, tables,
  emphasis, links, or fenced code
- **THEN** the assistant answer displays those structures with safe styling
- **AND** the source answer remains recoverable for copying or plain-text
  fallback

### Requirement: User can inspect persisted Agent runs

The desktop workspace SHALL display each Agent run as a compact execution
group with its status, duration or timestamps when available, event count, and
expand/collapse control. Inside the group it SHALL render ordered model,
tool, result, visual, and failure events, correlating tool evidence by call
identifier.

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

#### Scenario: Legacy or incomplete history is explicit

- **WHEN** a run has no recoverable events, has an event-history gap, or was
  interrupted by a Gateway restart
- **THEN** the UI shows an explicit unavailable, incomplete, or interrupted
  state
- **AND** it does not fabricate missing execution steps

### Requirement: User can observe a live Agent run

The desktop workspace SHALL start a run through the backend boundary and render
its current state as connecting, running, completed, failed, interrupted, or
unavailable. While a run is active, the workspace SHALL merge historical
replay and live events into one ordered execution group without replacing the
primary conversation with raw protocol data.

#### Scenario: User submits a Gateway-backed message

- **WHEN** the user sends non-empty text with zero or more selected attachment
  IDs in Gateway mode
- **THEN** the workspace immediately shows the user request and a running
  state, then consumes the associated run events until a terminal result

#### Scenario: Execution details arrive during a run

- **WHEN** the Gateway emits model, tool-call, tool-result, progress, or visual
  observation events
- **THEN** the workspace adds corresponding expandable execution details in
  order and keeps the main answer area scannable

#### Scenario: Run completes successfully

- **WHEN** the associated run emits a final answer
- **THEN** the workspace renders the Markdown assistant answer, marks the run
  completed, and refreshes the session summary without duplicating the user
  message or removing its execution group

#### Scenario: Run reconnects after an event-stream interruption

- **WHEN** the event connection becomes unavailable while the run is active
- **THEN** the workspace retains rendered events, requests missing events after
  the last known sequence when possible, and resumes the run state
- **AND** it reports an explicit history-gap state if replay is unavailable

#### Scenario: Run fails or Gateway becomes unavailable

- **WHEN** the run emits a bounded failure or the event connection cannot be
  recovered
- **THEN** the workspace marks the run as failed or unavailable, shows
  Simplified Chinese recovery feedback, and preserves all prior events and
  completed conversation content

### Requirement: User can inspect live visual observations

The workspace SHALL render visual-observation events with their tool name,
caption, and an authorized image preview when the observation resource is
available. Persisted observation metadata and artifact availability SHALL be
distinct from user-local attachment previews, and expired artifacts SHALL show
an explicit bounded state.

#### Scenario: Generated observation is available

- **WHEN** a run emits a visual observation with an authorized observation ID
- **THEN** the workspace retrieves and displays the bounded image preview
  alongside its caption and execution context
- **AND** the observation remains discoverable when the run is reopened if its
  persisted artifact is still within policy

#### Scenario: Observation resource is unavailable or expired

- **WHEN** the observation ID is missing, unauthorized, or its artifact has
  expired
- **THEN** the workspace shows the persisted caption and bounded unavailable
  state without displaying a broken URL or exposing a local path
