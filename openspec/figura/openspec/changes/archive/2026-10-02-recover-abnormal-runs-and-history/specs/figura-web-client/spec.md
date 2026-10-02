## MODIFIED Requirements

### Requirement: Run controls follow Figura's durable lifecycle and event cursor
Figura mode SHALL create Runs with a fresh idempotency key per user submission, prevent a distinct second submission while a Session has a running Run, and restore a running Run after reload by reading durable state. It SHALL consume replayable lifecycle events from the last received sequence, reconnect through the shared run lifecycle controller, and reload Session detail after a terminal event. The UI SHALL present `running`, `completed`, `failed`, and `interrupted` outcomes and SHALL distinguish queued, executing, recovering and stopping activity according to safe Gateway projections, without classifying every unresolved attempt as reconciliation. It SHALL NOT automatically create a replacement Run, replay an uncertain Provider call, or invoke an unresolved tool action.

#### Scenario: Follow a Run to completion
- **WHEN** a submitted Run emits ordered lifecycle events and reaches a terminal state
- **THEN** the UI converges on the durable Run status and reloads the Session's accepted answer

#### Scenario: Reconnect after a network interruption
- **WHEN** the browser loses its event stream and reconnects
- **THEN** it resumes after the last received sequence and catches up without duplicating Run lifecycle events

#### Scenario: Reload while a Run is active
- **WHEN** the browser reloads after Run creation but before a terminal event
- **THEN** it restores the existing Run and its event cursor without submitting the user message again

#### Scenario: A tool action is being recovered
- **WHEN** the Gateway reports recovery of a still-running Run
- **THEN** the UI shows that activity, permits only advertised stop control, and offers no manual replay or duplicate Run action

#### Scenario: Reload after stop acceptance
- **WHEN** the browser reloads while a stop request is durable but the Run remains running
- **THEN** the UI restores stopping, disables repeated stop and submission, and follows the same Run until its terminal outcome

#### Scenario: Continue after abnormal termination
- **WHEN** a Run reaches failed or interrupted and Gateway confirms execution ownership release
- **THEN** the UI preserves committed output, displays the safe reason, and allows a fresh user submission in the same Session without reopening the old Run

### Requirement: Figura mode exposes only supported workspace actions
Figura mode SHALL show Session creation, Session selection, Session deletion when permitted by its Gateway lifecycle rules, image attachment, Provider selection, Run submission, advertised cooperative stop, durable Run status, and committed chart-render output with full-size preview and download. It SHALL NOT offer evaluation workspaces, retry, resume, manual tool replay, or arbitrary reconciliation controls. Cooperative stop SHALL be enabled only through the specified Figura stop capability. This visibility rule SHALL NOT remove capabilities from the existing ChartAgent mode.

#### Scenario: Render the supported Figura capability set
- **WHEN** the user opens Figura mode
- **THEN** the workspace presents the supported Session, attachment, Provider, Run, and committed chart-render capabilities

#### Scenario: Use a ChartAgent-only capability
- **WHEN** the user opens ChartAgent mode
- **THEN** its existing evaluation, preview, and supported Run controls remain available under the existing client contract

#### Scenario: Preserve other client modes
- **WHEN** the shared workspace supports Figura, ChartAgent and mock clients
- **THEN** stop is shown only when the active client implements it and existing other-mode controls retain their behavior

## ADDED Requirements

### Requirement: Cooperative stop does not imply immediate completion
Figura mode SHALL send stop through the client abstraction only when availableActions advertises it. It SHALL show stopping after acceptance, prevent repeated stop and distinct submissions while running, and converge from durable state and sequenced events rather than local timeout. It SHALL refresh running activity through bounded reads, including after reconnect. A non-returning handler SHALL remain visibly stopping; the UI SHALL NOT claim it has been forcibly terminated or allow deletion on stop acceptance alone.

#### Scenario: Stop from the workspace
- **WHEN** a user selects the advertised stop action
- **THEN** the UI sends one Session-scoped request through its client and waits for the durable terminal outcome

#### Scenario: Stop request response is lost
- **WHEN** the network disconnects after stop was persisted
- **THEN** reconnect restores durable stopping without creating another Run

#### Scenario: A handler does not return
- **WHEN** the tool remains active after stop acceptance
- **THEN** the UI keeps stopping and explains that it is waiting for the current step instead of presenting stopped
