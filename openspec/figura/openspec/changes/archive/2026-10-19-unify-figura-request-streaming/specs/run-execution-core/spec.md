## ADDED Requirements

### Requirement: Provider attempts record transport phases without persisting stream fragments
For every Provider request purpose, Figura SHALL persist one canonical attempt lifecycle linked to its logical request. An active attempt SHALL identify its current phase and record available timestamps for dispatch start, connection establishment, request transmission, response opening, first stream event, last transport activity, and completion. Terminal records SHALL include bounded failure phase/code, HTTP status when available, Provider request identity when safe, retry lineage, and byte or usage counters when available. Figura SHALL NOT persist individual stream fragments, raw request or response bodies, credentials, reasoning text, or partial tool arguments as attempt diagnostics. A started attempt recovered after owner exit SHALL be closed as outcome-unknown before any eligible replacement is claimed.

#### Scenario: Diagnose a request stalled before response opening
- **WHEN** a Provider request has been transmitted but no response headers or stream event has arrived
- **THEN** the attempt records the latest known phase and timestamps without reporting an unobserved remote cause

#### Scenario: Record an active stream
- **WHEN** a Provider emits stream events
- **THEN** the attempt remains active, updates its phase activity metadata, and does not create one durable Runtime record per event

#### Scenario: Recover an abandoned stream attempt
- **WHEN** the owning execution process is confirmed inactive and the attempt remains started
- **THEN** Figura closes it as outcome-unknown before applying the logical request retry policy

### Requirement: Only a complete Provider stream commits model effects
Figura SHALL commit a normalized model response only after a valid terminal stream event and complete response validation. The accepted response, optional continuation, complete tool-call batch, and next checkpoint SHALL be committed atomically. Partial assistant text, reasoning fragments, usage fragments, and incomplete tool calls SHALL remain transient and SHALL NOT advance the checkpoint or create executable tool facts.

#### Scenario: Commit a complete streamed tool-call response
- **WHEN** the stream terminates validly and every tool call is complete and valid
- **THEN** Figura commits the model response, continuation, tool-call batch, and checkpoint in one transaction

#### Scenario: Discard effects from an interrupted stream
- **WHEN** a stream fails before a valid terminal event
- **THEN** Figura commits no model response, continuation, or tool-call fact from that attempt
