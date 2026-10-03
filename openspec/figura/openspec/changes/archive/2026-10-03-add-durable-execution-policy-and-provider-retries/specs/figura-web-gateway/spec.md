## MODIFIED Requirements

### Requirement: Run creation is asynchronous, idempotent, and Session-scoped
The Gateway SHALL accept a Run request protected by the shared complete-input JSON guard containing nonempty text, an ordered list of owned attachment IDs, and an allowlisted `providerId`; it SHALL require an `Idempotency-Key` header and SHALL resolve the fixed model ID on the server. After the existing runtime atomically persists the Run, input, checkpoint, idempotency mapping, and creation event, the Gateway SHALL dispatch the same Run to the Figura Agent asynchronously and return its opaque Run ID and persisted status without waiting for Provider completion. It SHALL allow at most one running Run per Session, preserve same-key/same-payload idempotent replay, reject key reuse with a different payload, and SHALL NOT dispatch a Provider request from the HTTP handler itself.

Run request JSON SHALL use bounded reception with the shared execution-payload configuration, independently of the Sources upload-byte contract. The Gateway SHALL not restore deleted text micro limits or a generic sixteen-attachment-reference count.

#### Scenario: Start a Figura Run from the browser
- **WHEN** the browser submits a valid request with a configured Provider and an idempotency key
- **THEN** the Gateway returns an accepted response containing the persisted Run ID, Session ID, `running` status, Provider ID, and fixed model ID while Agent execution proceeds asynchronously

#### Scenario: Retry a request after losing the HTTP response
- **WHEN** the browser repeats the same Session request with the same idempotency key and payload
- **THEN** the Gateway returns the original Run and ensures its execution is scheduled at most once by the active Gateway process

#### Scenario: Reject conflicting or concurrent Run creation
- **WHEN** a key is reused with different text, attachment order, or Provider, or a distinct Run is requested while another Run in the Session is running
- **THEN** the Gateway returns a bounded conflict response without creating another Run or dispatching another execution

#### Scenario: Reject a missing Provider configuration or invalid input
- **WHEN** the request selects an unconfigured/unsupported Provider, supplies an invalid model selection, unknown Session, invalid attachment, empty text, or malformed idempotency key
- **THEN** the Gateway rejects the request before creating a Run or scheduling execution

### Requirement: Gateway recovery follows durable Run checkpoint safety
The Gateway SHALL schedule normal execution, startup takeover, and bounded periodic/exit compensation through one coordinated execution boundary. Scheduling SHALL preserve Run identity, checkpoint safety, queue capacity, and cross-process ownership. Orphaned Provider attempts SHALL first be closed as unknown, then follow the guarded durable replacement contract or fail safely when replacement is unavailable. Eligible orphaned tools SHALL follow bounded declared-effect recovery; unavailable recovery SHALL terminate safely. Durable stop SHALL take precedence. A safe projection SHALL distinguish queued, executing, recovering, stopping, and terminal activity without executing work during reads. Storage or integrity failure SHALL remain fail-closed and SHALL NOT be reported as successful termination.

Scheduling SHALL yield a Run after one committed external action and rotate eligible Runs so a long task does not monopolize workers across action boundaries. Persisted retry waits SHALL consume neither a worker nor a queued execution slot, and not-yet-due retries SHALL be skipped except for accepted stop coordination. The existing bounded worker/queue capacity and Run event identities SHALL be preserved. Read-only endpoints SHALL not execute, claim, schedule or reconcile work.

#### Scenario: Resume a Run with a safe pending action
- **WHEN** the Gateway starts and finds a running Run whose checkpoint can continue under existing Agent rules
- **THEN** it schedules execution from that checkpoint without creating another Run or duplicating committed facts

#### Scenario: Recover an uncertain Provider attempt
- **WHEN** a started Provider attempt has no committed outcome after the prior execution owner exits
- **THEN** the Agent preserves the unknown fact and schedules a guarded replacement only when the original request binding and allowance permit it

#### Scenario: Recover or close an orphaned tool attempt
- **WHEN** a prior owner has exited and the running Run has an unresolved tool attempt
- **THEN** coordinated execution either safely recovers it within its persisted per-call recovery allowance or terminates with an explicit reason without duplicating effects

#### Scenario: Queue capacity becomes available
- **WHEN** a persisted running Run could not be queued during startup or a previous scheduling attempt
- **THEN** bounded compensation later schedules it without creating another Run or busy-looping

#### Scenario: Execution exits unexpectedly
- **WHEN** a task exits while the Run remains running
- **THEN** the Gateway rechecks durable state and coordinates bounded compensation instead of silently discarding responsibility

#### Scenario: Rotate more Runs than queue capacity
- **WHEN** more independent running Sessions are ready than the worker and queue capacity combined
- **THEN** completed slices rejoin behind eligible peers so repeatedly active older Runs do not indefinitely prevent newer Runs from executing

#### Scenario: Release a retry waiter
- **WHEN** a retry checkpoint is persisted with a future eligible time
- **THEN** its worker and scheduling slot are released and other ready Sessions can execute

#### Scenario: Stop bypasses retry due time
- **WHEN** a waiting Run receives a durable stop request before its next eligible time
- **THEN** the Gateway schedules stop coordination promptly without dispatching the retry or waiting until due
