## ADDED Requirements

### Requirement: Gateway runtime preserves chart-review lifecycle integrations

A Gateway-managed Agent runtime that supports generated-chart review SHALL
preserve the per-run operations needed to persist candidate images and their
ChartSpecs, resolve those review inputs during review or recovery, and publish
execution-gate updates. Required operations SHALL NOT be silently omitted when
constructing the runtime. A candidate requiring review SHALL remain unpublished
until its review input has been persisted and the required review has completed.
Missing runtime integration SHALL be distinguishable from an actual candidate
storage failure; genuine persistence failures SHALL remain fail-closed.

#### Scenario: Default Gateway runtime prepares a reviewable candidate

- **WHEN** a Gateway-managed run renders a candidate whose policy requires review
- **THEN** the candidate image and the exact ChartSpec represented by it are durably associated with that candidate before review consumes them
- **AND** the review lifecycle's gate updates are propagated to the owning run
- **AND** the candidate is not published until review permits publication

#### Scenario: Review inputs remain resolvable during recovery

- **WHEN** a Gateway-managed review resumes or restores a candidate
- **THEN** the runtime can resolve the same stored image and ChartSpec using the candidate's bounded run, candidate, review, and digest references
- **AND** the restored review state continues to control the run's publication gate

#### Scenario: Missing integration is not reported as a storage write failure

- **WHEN** a Gateway runtime cannot provide a required candidate-review or gate integration
- **THEN** the run reports a bounded runtime-integration failure and does not misclassify the condition as `candidate_storage_failure`
- **AND** no candidate is published

#### Scenario: Actual candidate persistence failure remains fail-closed

- **WHEN** the configured candidate persistence operation is invoked but durable storage fails or rejects the candidate
- **THEN** the review reports a bounded candidate-storage failure
- **AND** the candidate remains unpublished
