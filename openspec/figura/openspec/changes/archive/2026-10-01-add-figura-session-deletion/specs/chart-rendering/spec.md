## ADDED Requirements

### Requirement: Session deletion removes its private ChartFigure render files
Figura SHALL remove the private render PNG for every durable render tool call belonging to a permanently deleted Session. The operation SHALL leave render files belonging to other Sessions unchanged. If Session deletion rolls back, staged render files SHALL be restored; if the database deletion commits, staged files SHALL be permanently removed or retained only in inaccessible private cleanup storage for startup reconciliation.

#### Scenario: Remove committed render files with their Session
- **WHEN** a Session with one or more committed ChartFigure renders is permanently deleted
- **THEN** its render content endpoint no longer resolves those PNG files and another Session's render files remain readable

#### Scenario: Remove a staged render after a committed deletion
- **WHEN** the process stops after Session deletion commits but before staged render files are physically unlinked
- **THEN** startup reconciliation removes those inaccessible staged files and does not restore them

#### Scenario: Restore renders after a rolled-back deletion
- **WHEN** the Session deletion transaction fails after render files have been staged
- **THEN** Figura restores those files and their existing render reads continue to succeed
