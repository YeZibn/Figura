## ADDED Requirements

### Requirement: A terminal Session and its Runtime facts can be purged as one aggregate
Runtime SHALL allow permanent deletion of an existing Session only when none of its Runs is `running`. A successful aggregate deletion SHALL remove the Session and all Runtime-owned data for its Runs, including execution records, tool facts, checkpoints, events, Provider attempts, continuations, and idempotency mappings, in one SQLite transaction. While a Session exists, individual immutable execution facts SHALL remain non-deletable; deletion authorization SHALL apply only to the complete Session aggregate. If the transaction fails, no Runtime-owned row in the aggregate SHALL be removed.

#### Scenario: Purge a terminal Session
- **WHEN** the deletion operation targets a Session whose Runs are all terminal
- **THEN** the Session and every Runtime-owned row belonging to those Runs are removed together

#### Scenario: Reject a Session containing a running Run
- **WHEN** the deletion operation targets a Session with a `running` Run
- **THEN** Runtime rejects the operation and retains the Session and all Runtime facts

#### Scenario: Preserve fact immutability outside aggregate deletion
- **WHEN** an operation attempts to delete an individual Run fact without deleting its owning Session aggregate
- **THEN** Runtime rejects the deletion and retains the fact

#### Scenario: Roll back a failed aggregate purge
- **WHEN** a database failure occurs before the Session deletion transaction commits
- **THEN** the transaction leaves the Session, Runs, and their Runtime facts intact
