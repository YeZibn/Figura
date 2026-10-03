# provider-request-retries Specification

## Purpose

Defines durable recovery of temporary Provider request failures without limiting the number of normal model decisions in a Run, duplicating accepted model responses, or silently changing a request after restart.

## Requirements

### Requirement: Retry allowances belong to one immutable logical request
Figura SHALL distinguish each logical model request from its physical Provider attempts. Before first dispatch, it SHALL durably bind the request to the owning Run and committed prefix, Provider/model, endpoint binding, exact prepared-request fingerprint, options, request contract and asset identities, generation-only classification, and a maximum of four claimed physical attempts including the initial attempt. Subsequent attempts SHALL preserve that binding and use consecutively numbered identities; crashes and restarts SHALL NOT reset the allowance. There SHALL be no cumulative Run retry or model-request allowance.

#### Scenario: Continue beyond eight normal model decisions
- **WHEN** a Run reaches its ninth distinct valid model decision
- **THEN** the decision can claim its own initial attempt and is not rejected because earlier decisions used eight or more attempts

#### Scenario: Restart after three attempts
- **WHEN** one logical request has three claimed attempts before restart
- **THEN** it has at most one remaining physical attempt and cannot obtain a fresh four-attempt allowance

#### Scenario: Reconstruct a changed request
- **WHEN** endpoint, Provider/model, prepared payload, required asset or contract identity cannot match the original binding
- **THEN** Figura fails safely without sending a modified replacement request or selecting another Provider

### Requirement: Only classified temporary failures allow automatic Provider retry
Figura SHALL automatically retry only positively classified temporary connection, transmission, rate-limit or service failures. Local validation/configuration errors, authentication and quota exhaustion, unsupported requests, deterministic connection configuration errors, invalid normalized responses and unclassified program errors SHALL NOT trigger automatic retry. Outcome certainty and temporary classification SHALL remain separate facts. SDK and transport retries SHALL remain disabled; the durable execution owner SHALL be the only automatic retry owner.

#### Scenario: Retry a temporary rate limit
- **WHEN** the Provider definitively rejects a request for a temporary rate limit and the logical allowance remains
- **THEN** Figura records a known failure and schedules a replacement under the same binding

#### Scenario: Do not retry exhausted credit
- **WHEN** a 429 response carries an allowlisted permanent quota or credit-exhaustion code
- **THEN** Figura terminates safely rather than treating the HTTP status alone as a temporary rate limit

#### Scenario: Do not repair a malformed response by network retry
- **WHEN** a response contains malformed tool arguments or a rejected finish reason such as length
- **THEN** Figura follows the invalid-response contract without automatic repair, continuation generation or tool execution

#### Scenario: Do not classify an arbitrary exception as temporary
- **WHEN** an exception has no recognized temporary transport or Provider classification
- **THEN** Figura uses a safe permanent/internal failure path and does not automatically resend it

### Requirement: Unknown generation outcomes allow only guarded replacement
An attempt with no definitive remote result SHALL remain outcome unknown. Only a request durably classified as generation-only SHALL be eligible for a replacement after its previous local dispatch has returned or the previous execution owner is proven inactive. Figura SHALL close the old attempt before claiming a new identity and SHALL NOT rewrite unknown history as a known rejection. Each logical request SHALL accept at most one response and its associated continuation and tool-intent batch. A stale response SHALL never create another observation or execute tools. Requests with possible remote side effects and legacy attempts without reproducible bindings SHALL NOT be automatically replaced after unknown outcomes.

#### Scenario: Replace an unknown generation after owner exit
- **WHEN** the old owner is confirmed inactive, the exact generation-only request can be rebuilt, stop is absent and an attempt remains
- **THEN** Figura preserves the old unknown attempt and can claim one new physical attempt for that logical request

#### Scenario: Old handler is still active
- **WHEN** an old timestamp or caller timeout is observed but the original local execution owner is still active
- **THEN** Figura claims no replacement and does not use elapsed time as proof of owner exit

#### Scenario: Reject a late old response
- **WHEN** an already closed old attempt supplies a late response after replacement was scheduled or accepted
- **THEN** Figura rejects it without adding a second response, continuation or tool batch

#### Scenario: Exhaust an unknown operation
- **WHEN** the fourth claimed physical attempt ends with no definitive outcome
- **THEN** Figura preserves all attempts and terminates with an explicit unknown-Provider-outcome reason without a fifth claim

### Requirement: Retry waiting is durable and stop takes precedence
For eligible failures before the fourth attempt, Figura SHALL persist the closed attempt, next eligible UTC time and retry checkpoint atomically. It SHALL use exponential backoff starting at one second with full jitter and a thirty-second exponential cap, and SHALL honor a valid later Retry-After without shortening it. Waiting SHALL release execution workers and ownership. Restart SHALL preserve the due time. Every retry claim SHALL check the current checkpoint, allowance, ownership, request binding and durable stop in the same arbitration boundary. Reads SHALL neither schedule nor dispatch retries.

#### Scenario: Resume a wait after restart
- **WHEN** a store is reopened before the persisted retry time
- **THEN** reads return unchanged facts and execution does not claim the next attempt until due

#### Scenario: Respect a service retry delay
- **WHEN** a valid Retry-After exceeds the local jitter delay
- **THEN** the next eligible time respects the service delay and no worker sleeps while holding Run ownership

#### Scenario: Stop while waiting
- **WHEN** stop is durably accepted before a retry claim
- **THEN** execution interrupts promptly through coordination without waiting for the retry time or dispatching another request
