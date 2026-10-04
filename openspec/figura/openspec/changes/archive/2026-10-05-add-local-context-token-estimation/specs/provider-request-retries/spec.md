## ADDED Requirements

### Requirement: Logical requests preserve optional context estimates
Before first dispatch, a newly bound logical request SHALL persist its available context estimate with non-negative integer input tokens, optional positive integer context capacity and non-empty estimator version. This metadata SHALL remain independent of the prepared payload fingerprint, request contract and retry arbitration. Physical retries and restart recovery SHALL reuse the original snapshot without accumulating usage, updating capacity or requiring estimation success. Older bindings without this metadata SHALL remain readable and retryable under their original contracts; reads SHALL NOT backfill them.

#### Scenario: Retry a measured logical request
- **WHEN** a request with an estimate retries after a temporary failure or service restart
- **THEN** every attempt refers to the same stored estimate and the original exact-request checks remain in force

#### Scenario: Read or retry a legacy binding
- **WHEN** a version-one binding has no context estimation metadata
- **THEN** it remains readable and its existing retry eligibility is unchanged without synthesized estimation metadata

#### Scenario: Configuration changes before recovery
- **WHEN** the local capacity or estimator version changes after the first attempt
- **THEN** recovery retains the original estimate and neither rejects the retry nor rewrites the binding solely because of the display metadata change
