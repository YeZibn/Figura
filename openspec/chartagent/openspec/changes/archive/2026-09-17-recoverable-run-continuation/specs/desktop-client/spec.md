## ADDED Requirements

### Requirement: User can choose resume separately from reconnect and retry

The desktop client SHALL distinguish transport reconnect, explicit continuation,
and fresh retry in its run presentation. For an interrupted or failed run, it
SHALL display whether a safe checkpoint is available, show bounded recovery
block reasons in Simplified Chinese, and expose a `继续执行` action only when
the Gateway reports resume eligibility. Resume SHALL create and display a new
child run while retaining the parent timeline; reconnect SHALL never create a
new run.

#### Scenario: Recoverable interruption shows continue action

- **WHEN** a restored run is interrupted and exposes an available checkpoint
- **THEN** the client shows the interrupted reason and a `继续执行` action
- **AND** it also keeps `重新尝试` available as a from-scratch alternative

#### Scenario: Resume displays parent and child runs

- **WHEN** the user chooses `继续执行`
- **THEN** the client displays the new child run with a bounded resume
  relationship to the parent
- **AND** the original timeline and terminal state remain inspectable

#### Scenario: Blocked recovery explains the fallback

- **WHEN** a run has an uncertain in-flight operation or an expired checkpoint
- **THEN** the client hides or disables `继续执行`
- **AND** it shows a bounded Chinese explanation with the option to
  `重新尝试`

#### Scenario: Reconnect remains same-run recovery

- **WHEN** the event stream disconnects while a run is still active
- **THEN** the client reconnects with the same run identity and cursor
- **AND** it does not show the disconnect as a resume or create another user
  message
