## ADDED Requirements

### Requirement: Runs within a Session are created sequentially
Figura SHALL allow at most one `running` Run per Session. Creating a new Run SHALL atomically reject a distinct request while that Session already has a running Run, without writing a Run or any of its facts. An idempotent replay that matches an existing Run SHALL return that Run, including while it is running. A new Run MAY be created after all prior Runs in the Session are terminal.

#### Scenario: Reject a second active Run in the same Session
- **WHEN** a caller submits a new, non-idempotent Run request while another Run in that Session has status `running`
- **THEN** Figura rejects the request without creating a Run, input record, checkpoint, idempotency mapping, or event

#### Scenario: Preserve idempotent replay of the active Run
- **WHEN** a caller repeats the original creation request with the same Session, idempotency key, and request content while its Run is still running
- **THEN** Figura returns the original Run and creates no additional Run or facts

#### Scenario: Create the next Run after the prior Run is terminal
- **WHEN** all existing Runs in a Session are completed, failed, or interrupted
- **THEN** Figura may create a new Run with the next Session ordinal
