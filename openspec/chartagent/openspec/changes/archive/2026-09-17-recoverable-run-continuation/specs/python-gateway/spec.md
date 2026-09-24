## ADDED Requirements

### Requirement: Gateway exposes safe run recovery and explicit resume

The Gateway SHALL expose bounded recovery metadata for a run, including
checkpoint availability, recovery phase, and a safe blocked reason when
applicable. It SHALL provide an authorized resume operation at
`/api/v1/sessions/{sessionId}/runs/{runId}/resume`. A valid resume request SHALL
use a new idempotency key, create a new child run from a recoverable checkpoint,
and preserve the parent terminal outcome. The Gateway SHALL reject unavailable,
expired, cross-session, or uncertain recovery with stable safe errors.

#### Scenario: Resume returns a child run

- **WHEN** an authorized client resumes an interrupted run with an available
  checkpoint
- **THEN** the Gateway returns a new running run identity with a `resume`
  parent relationship
- **AND** it does not change the parent run's terminal summary or events

#### Scenario: Resume request is idempotent

- **WHEN** a client repeats the same resume request with the same idempotency
  key and parent checkpoint
- **THEN** the Gateway returns the original child run and current state
- **AND** it does not enqueue a second Agent continuation

#### Scenario: Recovery is blocked safely

- **WHEN** the parent has no valid checkpoint, an expired reference, or an
  uncertain in-flight operation without a replay-safe contract
- **THEN** the Gateway returns a bounded recovery-unavailable or
  recovery-blocked error with a stable reason
- **AND** it does not start a new Agent execution

#### Scenario: Resume authorization and lineage are enforced

- **WHEN** a client resumes a run from another session or submits a malformed
  checkpoint or idempotency identity
- **THEN** the Gateway rejects the request before execution
- **AND** it does not expose the other session's checkpoint or run data
