## MODIFIED Requirements

### Requirement: Retry and resume create attributable child runs

The system SHALL distinguish reconnect, resume, and retry. Reconnect SHALL
retain the same run identity and idempotency context. An explicit resume SHALL
require a valid recoverable checkpoint, create a new run identity and new
idempotency context, and retain a bounded `resume` parent relationship. An
explicit retry SHALL create a new run identity and new idempotency context
from the original request, retaining a bounded `retry` parent relationship and
the prior run's terminal reason. Neither operation SHALL mutate the parent run
or append new execution events to it.

#### Scenario: User resumes a recoverable interrupted run

- **WHEN** the user explicitly resumes an interrupted run with an available
  safe checkpoint
- **THEN** the system creates a new child run with a new identity
- **AND** the child records the prior run as its `resume` parent

#### Scenario: Resume is unavailable for uncertain work

- **WHEN** a run has no valid checkpoint or contains an uncertain operation
  without a replay-safe contract
- **THEN** resume is rejected with a bounded recovery reason
- **AND** the system leaves the original run unchanged and offers retry as a
  separate operation

#### Scenario: User retries from the original request

- **WHEN** the user explicitly retries a failed or interrupted run
- **THEN** the Gateway creates a new run with a new identity and a `retry`
  parent relationship
- **AND** the new run starts from the original user request rather than the
  checkpoint

#### Scenario: Reconnect is not resume or retry

- **WHEN** the client loses an event connection but has not requested resume or
  retry
- **THEN** the client only resumes the existing run by identity and sequence
- **AND** no new user message or Agent execution is created
