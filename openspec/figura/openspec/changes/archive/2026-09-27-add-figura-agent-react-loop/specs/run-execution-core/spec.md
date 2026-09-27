## ADDED Requirements

### Requirement: Provider model actions are durably claimed before dispatch
Before an Agent sends a provider request for a Run whose checkpoint points to a model action, Figura SHALL atomically record one bounded provider-attempt identity and advance the checkpoint to that attempt. The claim SHALL compare the expected checkpoint revision and current action in the same transaction. A provider request SHALL NOT be dispatched unless its claim commits, and only one attempt SHALL be active for a Run at a time. Attempt metadata SHALL not contain the serialized prompt, tool schemas, credentials, raw endpoint, or provider response body.

#### Scenario: Claim the current model action
- **WHEN** the expected checkpoint revision is current and points to a model action
- **THEN** Figura records the attempt and advances the checkpoint to the matching provider-attempt action atomically

#### Scenario: Claim races with another executor
- **WHEN** two callers claim the same model action using the same checkpoint revision
- **THEN** at most one claim commits and the caller whose claim fails does not dispatch a provider request

#### Scenario: Attempt claim cannot be persisted
- **WHEN** storage fails before the provider-attempt claim commits
- **THEN** Figura leaves the prior checkpoint and facts unchanged and sends no provider request

### Requirement: Provider attempt outcomes are linked atomically to Run progress
A claimed provider attempt SHALL transition from `started` to exactly one terminal attempt outcome. A valid normalized response SHALL be linked to its attempt in the same transaction that appends the response, optional private continuation, associated tool-call facts, and next checkpoint. A known provider failure SHALL be recorded with bounded failure metadata and atomically fail the Run. An unknown provider outcome SHALL atomically mark the attempt unknown and fail the Run with terminal code `provider_outcome_unknown`. No terminal attempt outcome SHALL be replaced by another outcome.

#### Scenario: Commit a provider response
- **WHEN** the checkpoint points to a matching started provider attempt and a valid normalized response is committed
- **THEN** Figura links the attempt to the new response and commits the response, continuation, tool intents, and checkpoint in one transaction

#### Scenario: Record a known provider failure
- **WHEN** the provider returns a definitive failure for a started attempt
- **THEN** Figura records the bounded failure code, marks the attempt as a known failure, and commits the Run's failed state and terminal event atomically

#### Scenario: Record an unknown provider outcome
- **WHEN** the provider call fails without a definitive remote outcome
- **THEN** Figura marks the attempt as outcome unknown and commits a failed Run with terminal code `provider_outcome_unknown`, without resending the request

#### Scenario: Reject an attempt result for stale progress
- **WHEN** a response or failure refers to an attempt that is not the current started attempt at the expected checkpoint revision
- **THEN** Figura rejects the transition without partially changing the attempt, Run facts, checkpoint, or events

### Requirement: Recovery never resends a started provider attempt
Reading a Run SHALL remain side-effect free. After the previous per-Run execution owner is confirmed inactive, if a running Run's checkpoint references a provider attempt that remains `started`, recovery SHALL atomically mark that attempt outcome unknown and fail the Run with `provider_outcome_unknown`. Figura SHALL NOT infer that the request was never sent and SHALL NOT retry or select another provider/model.

#### Scenario: Recover a started attempt after process restart
- **WHEN** recovery acquires the Run's exclusive execution lock and finds a started provider attempt without a committed outcome
- **THEN** Figura records an unknown outcome and fails the Run without issuing a provider request

#### Scenario: Read an unresolved provider attempt
- **WHEN** a caller only reads a Run whose current checkpoint references a started provider attempt
- **THEN** Figura returns the persisted state without changing it or contacting the provider

#### Scenario: Preserve old Runs during schema migration
- **WHEN** a store containing schema-version-3 Runs is migrated to the provider-attempt schema
- **THEN** existing Run identities, records, continuations, tool facts, checkpoints, and terminal states remain readable without inventing provider attempts for already committed responses
