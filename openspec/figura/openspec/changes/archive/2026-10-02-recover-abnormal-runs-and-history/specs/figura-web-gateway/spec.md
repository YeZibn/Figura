## MODIFIED Requirements

### Requirement: Gateway recovery follows durable Run checkpoint safety
The Gateway SHALL schedule normal execution, startup takeover, and bounded periodic/exit compensation through one coordinated execution boundary. Scheduling SHALL preserve Run identity, checkpoint safety, queue capacity, and cross-process ownership. Started Provider attempts with unknown outcomes SHALL fail without resending. Eligible orphaned tools SHALL follow bounded declared-effect recovery; unavailable recovery SHALL terminate safely. Durable stop SHALL take precedence. A safe projection SHALL distinguish queued, executing, recovering, stopping, and terminal activity without executing work during reads. Storage or integrity failure SHALL remain fail-closed and SHALL NOT be reported as successful termination.

#### Scenario: Resume a Run with a safe pending action
- **WHEN** the Gateway starts and finds a running Run whose checkpoint can continue under existing Agent rules
- **THEN** it schedules execution from that checkpoint without creating another Run or duplicating committed facts

#### Scenario: Recover an uncertain Provider attempt
- **WHEN** a started Provider attempt has no committed outcome after the prior execution owner exits
- **THEN** the Agent applies the existing unknown-outcome rule and does not send the Provider request again

#### Scenario: Recover or close an orphaned tool attempt
- **WHEN** a prior owner has exited and the running Run has an unresolved tool attempt
- **THEN** coordinated execution either safely recovers it within budget or terminates with an explicit reason without duplicating effects

#### Scenario: Queue capacity becomes available
- **WHEN** a persisted running Run could not be queued during startup or a previous scheduling attempt
- **THEN** bounded compensation later schedules it without creating another Run or busy-looping

#### Scenario: Execution exits unexpectedly
- **WHEN** a task exits while the Run remains running
- **THEN** the Gateway rechecks durable state and coordinates bounded compensation instead of silently discarding responsibility

### Requirement: Session deletion removes the owning Session as one bounded operation
The Gateway SHALL provide `DELETE /sessions/{sessionId}`. A successful deletion SHALL return `204` and make the Session, its Runs and execution facts, its attachment and Panel resources, and its ChartFigure render images unavailable through Figura APIs. The operation SHALL affect only the addressed Session. The Gateway SHALL reject an unknown Session with a bounded `404` response and SHALL reject deletion while any Run in the Session is `running` or an execution owner has not released ownership with a bounded `409` response. A rejected or failed deletion SHALL NOT be reported as successful. The operation SHALL follow the existing local-Origin and safe-error boundary.

#### Scenario: Delete a terminal Session
- **WHEN** the browser deletes an existing Session whose Runs are all terminal and whose execution ownership has been released
- **THEN** the Gateway returns `204` and subsequent Session, Run, attachment, Panel, timeline, and chart-render reads cannot retrieve its data

#### Scenario: Preserve another Session during deletion
- **WHEN** the browser deletes one terminal Session while another Session has data
- **THEN** only resources owned by the addressed Session are removed and the other Session remains readable

#### Scenario: Reject deletion while a Run is running
- **WHEN** the browser deletes a Session containing a `running` Run
- **THEN** the Gateway returns a bounded `409` response and leaves the Session and all of its resources available

#### Scenario: Reject an unknown Session
- **WHEN** the browser deletes an unknown Session ID
- **THEN** the Gateway returns a bounded `404` response without disclosing other Session data

#### Scenario: Recover from a failed deletion
- **WHEN** persistent deletion cannot commit
- **THEN** the Gateway returns a bounded failure and the Session remains readable with its associated data intact

#### Scenario: Stop acceptance is not deletion permission
- **WHEN** a stop request is accepted but an executor is still active
- **THEN** deletion returns a bounded conflict and leaves data available

## ADDED Requirements

### Requirement: Browser stop requests are Session-scoped and asynchronous
The Gateway SHALL expose POST /sessions/{sessionId}/runs/{runId}/stop under its existing local-Origin and bounded error rules. The request SHALL accept only an empty body or empty JSON object. It SHALL return 202 with the current safe Run projection and the original bounded stop request for acceptance or idempotent replay on a running Run, and 200 with the unchanged projection for a terminal Run. Unknown or cross-Session Run identities SHALL return bounded 404, invalid bodies 400, and storage failure a safe server error. Queue saturation SHALL NOT undo an accepted durable stop. Run projections SHALL include stopRequestedAt and availableActions, with stop offered only for running Runs without a request. Acceptance SHALL notify clients through the existing sequenced progress stream and SHALL NOT imply interruption is already complete.

#### Scenario: Accept stop during a tool call
- **WHEN** a browser stops a running Run with an executing tool
- **THEN** the request returns 202 and stopping activity while the genuine result may still commit before the terminal event

#### Scenario: Repeat stop
- **WHEN** the browser repeats stop for the same still-running Run
- **THEN** the response returns the original request identity with no duplicate control event

#### Scenario: Stop a terminal Run
- **WHEN** the addressed Run is already terminal
- **THEN** the response is 200 with unchanged outcome and no new stop request or event

#### Scenario: Private control projection
- **WHEN** a browser reads stop response, Session detail, history or SSE
- **THEN** no tool arguments, raw results, private continuation, local paths or exception text are exposed
