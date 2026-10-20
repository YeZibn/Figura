## MODIFIED Requirements

### Requirement: Retry allowances belong to one immutable logical request
Figura SHALL distinguish each logical Provider request from its physical attempts. Before dispatch, it SHALL durably bind the request to its owning Run, request purpose, committed prefix, Provider/model, endpoint identity, exact prepared-request fingerprint, options, request and asset contract identities, streaming protocol version, timeout and retry policy versions, generation-only classification, and a maximum of four claimed physical attempts including the initial attempt. Subsequent attempts SHALL preserve that binding and use consecutively numbered identities; crashes and restarts SHALL NOT reset the allowance. There SHALL be no cumulative Run retry or model-request allowance. Ordinary Agent turns, tool-call turns, and context-compaction summaries SHALL use this same logical-request binding and retry allowance.

#### Scenario: Continue beyond eight normal model decisions
- **WHEN** a Run reaches its ninth distinct valid model decision
- **THEN** the decision can claim its own initial attempt and is not rejected because earlier decisions used eight or more attempts

#### Scenario: Restart after three attempts
- **WHEN** one logical request has three claimed attempts before restart
- **THEN** it has at most one remaining physical attempt and cannot obtain a fresh four-attempt allowance

#### Scenario: Reconstruct a changed request
- **WHEN** endpoint, Provider/model, prepared payload, required asset, stream contract, timeout policy, or retry policy cannot match the original binding
- **THEN** Figura fails safely without sending a modified replacement request or selecting another Provider

#### Scenario: Apply the same binding to a compaction request
- **WHEN** a context-compaction operation dispatches its summary request
- **THEN** the summary request receives the same immutable Provider request binding and per-request attempt allowance as an ordinary Agent turn

### Requirement: Logical requests preserve optional context estimates
Before first dispatch, a newly bound logical request SHALL persist its available context estimate with non-negative integer input tokens, optional positive integer context capacity, and non-empty estimator version. This metadata SHALL remain independent of the prepared payload fingerprint, streaming contract, timeout policy, and retry arbitration. Physical retries and restart recovery SHALL reuse the original snapshot without accumulating usage, updating capacity, or requiring estimation success. A one-time schema migration SHALL move stored estimates into the canonical request record; runtime readers and dispatchers SHALL implement only the canonical request schema.

#### Scenario: Retry a measured logical request
- **WHEN** a request with an estimate retries after a temporary failure or service restart
- **THEN** every attempt refers to the same stored estimate and the original exact-request checks remain in force

#### Scenario: Configuration changes before recovery
- **WHEN** the local capacity or estimator version changes after the first attempt
- **THEN** recovery retains the original estimate and neither rejects the retry nor rewrites the binding solely because of the display metadata change

#### Scenario: Migrate stored request estimates
- **WHEN** the Runtime schema is upgraded
- **THEN** existing estimates are copied into the canonical request record without synthesizing missing values or keeping a legacy binding reader

## ADDED Requirements

### Requirement: One retry policy governs every Provider request purpose
Figura SHALL use one durable retry coordinator for ordinary Agent requests, tool-call model turns, and context-compaction summaries. It SHALL retry only classified temporary failures, honor a valid later `Retry-After`, keep the exact logical request binding, and use the existing bounded four-attempt allowance. It SHALL NOT impose a total generation deadline. A stream interrupted after request transmission SHALL be recorded as outcome-unknown; replacement SHALL occur only after the prior local owner is inactive and the attempt is closed, and SHALL retain the possibility of duplicate Provider billing when the Provider does not offer an idempotency contract.

#### Scenario: Retry an eligible interrupted generation stream
- **WHEN** a streamed generation ends with a classified temporary or unknown transport failure, the previous owner is inactive, and the logical request has an attempt remaining
- **THEN** Figura closes the old attempt, records its outcome certainty, and schedules a replacement with the same frozen request binding

#### Scenario: Do not retry a deterministic response failure
- **WHEN** a complete stream has invalid tool arguments, an unsupported finish reason, or a summary that fails its content contract
- **THEN** Figura does not create a network retry and follows the owning Agent or compaction failure policy

#### Scenario: Keep a live long-running request open
- **WHEN** a request has exceeded any progress-reporting threshold but its Provider transport remains live
- **THEN** Figura continues receiving the same attempt and does not cancel it because of total elapsed time alone

#### Scenario: Avoid duplicate execution after stream replacement
- **WHEN** an earlier attempt produced partial text or tool-call fragments before interruption and a replacement attempt is scheduled
- **THEN** Figura executes no partial tool call, accepts no partial model response, and associates any eventual complete response with exactly one attempt

#### Scenario: Close an in-flight request during the one-time contract migration
- **WHEN** migration finds an unfinished attempt bound to the removed non-streaming request contract
- **THEN** Figura closes it as outcome-unknown, interrupts its owning Run or compaction operation safely, and does not replay it through a legacy request path
