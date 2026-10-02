## MODIFIED Requirements

### Requirement: Unknown tool outcomes follow the declared replay effect
After recovery finds an attempt-start fact with no corresponding result, Figura SHALL treat the outcome as unknown and SHALL NOT assume the handler did not run. Recovery SHALL begin only after the prior execution owner is confirmed inactive and the committed registry version remains available. For replay_safe calls, Figura SHALL create a new attempt for the same logical call ID when recovery is requested. For idempotent_local_write calls, Figura SHALL create a new attempt only with the same stable idempotency key derived from canonical JSON `[run_id, call_id]`, and the handler contract SHALL return the prior operation result when that key was already applied. Figura SHALL expose this key only as `ToolContext.idempotency_key`; ToolRuntime SHALL refuse to invoke an idempotent local-write handler when the key is absent. For reconcile_required calls, Figura SHALL NOT invoke the handler again until a trusted reconciliation result is committed. Missing/unknown classifications and registry mismatches SHALL not be dispatched; the unresolved effect remains factual while automatic lifecycle coordination terminates safely once prior-owner exit is confirmed. A known failed result SHALL not be retried by this capability based solely on its retryable field.

The automatic execution owner SHALL recover only eligible calls after confirmed prior-owner exit, SHALL check durable stop before claiming each replay, and SHALL allow at most two automatic replays for one logical call across restarts. Automatic recovery SHALL return control after one call instead of dispatching the rest of a batch without stop checks. Known committed failures SHALL NOT be replayed merely because they are retryable. An unavailable registry or exhausted budget SHALL produce a bounded failed Run through its lifecycle owner. An uncertain reconcile_required call without a trusted reconciliation adapter SHALL end with an explicit unknown-outcome failure; it SHALL NOT be replayed or presented as rolled back.

#### Scenario: Replay a replay-safe call after owner exit
- **WHEN** recovery confirms the prior executor is inactive, the registry version matches, and an unresolved attempt is classified replay_safe
- **THEN** Figura starts a new attempt for the same logical call ID, records the new attempt number, and invokes the handler again only after the old execution owner is confirmed inactive

#### Scenario: Replay an idempotent local write
- **WHEN** recovery confirms the prior executor is inactive and an unresolved idempotent_local_write call is replayed
- **THEN** Figura uses the same stable Run/call idempotency key so a previously applied operation returns its prior result instead of creating a duplicate effect

#### Scenario: Require an idempotency key before local-write dispatch
- **WHEN** an idempotent_local_write invocation reaches ToolRuntime without `ToolContext.idempotency_key`
- **THEN** the runtime returns a bounded failure without invoking the handler

#### Scenario: Hold a call that requires reconciliation
- **WHEN** an unresolved attempt is classified reconcile_required
- **THEN** Figura does not invoke the handler again and allows only a trusted reconciliation outcome; the automatic lifecycle owner fails the Run explicitly when no trusted adapter is available

#### Scenario: Fail closed on an unverifiable attempt
- **WHEN** the replay classification is missing or unknown, the old executor may still be active, or the recorded registry version is unavailable
- **THEN** Figura does not dispatch the call and exposes a bounded unresolved state to the recovery owner

#### Scenario: Respect the persisted automatic recovery limit
- **WHEN** a logical call already has its initial attempt plus two automatic replay attempts without a result
- **THEN** automatic coordination does not claim another attempt and fails the Run with a fixed recovery-exhausted reason

#### Scenario: Keep local writes idempotent after partial effects
- **WHEN** a local-write handler applied its effect but no result was committed before its owner exited
- **THEN** eligible recovery uses the same original Run/call key and does not create a duplicate local object

#### Scenario: Stop before another recovered call
- **WHEN** stop is accepted while recovery of one call is in progress
- **THEN** its genuine result may commit but no remaining call is invoked before interruption

#### Scenario: No trusted reconciler
- **WHEN** an orphaned call requires reconciliation and no trusted tool-owned adapter is available
- **THEN** coordination fails with an explicit unknown-tool-outcome reason without dispatch or synthetic result
