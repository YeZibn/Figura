## ADDED Requirements

### Requirement: User can observe a live Agent run

The desktop workspace SHALL start a run through the backend boundary and render its current state as connecting, running, completed, failed, or unavailable. While a run is active, the workspace SHALL display bounded execution events in chronological order without replacing the primary conversation with raw protocol data.

#### Scenario: User submits a Gateway-backed message

- **WHEN** the user sends non-empty text with zero or more selected attachment IDs in Gateway mode
- **THEN** the workspace immediately shows the user request and a running state, then consumes the associated run events until a terminal result

#### Scenario: Execution details arrive during a run

- **WHEN** the Gateway emits model, tool-call, or tool-result events
- **THEN** the workspace adds corresponding expandable execution details in order and keeps the main answer area scannable

#### Scenario: Run completes successfully

- **WHEN** the associated run emits a final answer
- **THEN** the workspace renders the assistant answer, marks the run completed, and refreshes the session summary without duplicating the user message

#### Scenario: Run fails or Gateway becomes unavailable

- **WHEN** the run emits a bounded failure or the event connection becomes unavailable
- **THEN** the workspace marks the run as failed or unavailable, shows Simplified Chinese recovery feedback, and preserves prior completed conversation content

### Requirement: User can inspect live visual observations

The workspace SHALL render visual-observation events with their tool name, caption, and a safe temporary image preview when the observation resource is available. Observation previews SHALL remain distinct from user-local attachment previews and SHALL show an unavailable state when the temporary resource expires.

#### Scenario: Generated observation is available

- **WHEN** a run emits a visual observation with an authorized observation ID
- **THEN** the workspace retrieves and displays the bounded image preview alongside its caption and execution context

#### Scenario: Observation resource is unavailable

- **WHEN** the observation ID is expired, missing, or unauthorized
- **THEN** the workspace shows bounded metadata and an unavailable state without displaying a broken URL or exposing a local path

### Requirement: Backend boundary supports live events in mock and Gateway modes

The client boundary SHALL expose equivalent run and event contracts for mock and Gateway adapters. Mock mode SHALL simulate a bounded ordered event sequence without network access, while Gateway mode SHALL use the local event stream and SHALL NOT silently fall back to mock events.

#### Scenario: Mock mode exercises the live-run UI

- **WHEN** the client runs in mock mode and the user submits a message
- **THEN** the UI receives simulated running, execution-detail, and terminal events through the same boundary used by Gateway mode

#### Scenario: Gateway mode uses real events

- **WHEN** the client runs in Gateway mode and the local Gateway is ready
- **THEN** run state, execution details, visual observations, and final answer are driven by the Gateway contract rather than fabricated client data

#### Scenario: Gateway mode is not ready

- **WHEN** Gateway mode is selected but the local runtime is unavailable
- **THEN** the client shows the unavailable state and does not silently switch to mock mode

### Requirement: Unified startup selects the real client boundary

When the documented one-step Gateway development command is used, the desktop
client SHALL connect to the local Gateway event and session APIs without
requiring a second manual frontend command. The client SHALL expose startup or
connection failures in Simplified Chinese and SHALL preserve explicit mock mode
as a separate offline workflow.

#### Scenario: One-step Gateway startup reaches the workspace

- **WHEN** the unified development command starts the Gateway and the React client successfully
- **THEN** the workspace opens in Gateway mode and subsequent messages use real Gateway runs and SSE events

#### Scenario: One-step Gateway startup fails

- **WHEN** the unified command cannot make the Gateway ready
- **THEN** the workspace shows the unavailable state and does not fabricate mock sessions, tool events, or answers
