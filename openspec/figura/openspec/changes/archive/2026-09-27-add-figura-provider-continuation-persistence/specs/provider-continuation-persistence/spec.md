## Purpose

Persists provider-private continuation payloads with the exact Figura Run model response that produced them, so trusted execution code can reconstruct provider history after restart without exposing reasoning data through public Run projections.

## ADDED Requirements

### Requirement: Continuations are scoped to one committed model response
When a normalized provider response contains continuation data, Figura SHALL persist one private continuation payload linked to the same Run, model-response record, provider, and continuation format version. The model response SHALL contain an opaque optional continuation reference; a non-null reference SHALL resolve to exactly one payload for that response. A response without continuation data SHALL have no continuation reference or payload.

#### Scenario: Commit a provider continuation
- **WHEN** a valid provider response contains nonempty continuation data for the Run's selected provider and a supported format version
- **THEN** Figura stores the payload privately and links its opaque reference to that response record

#### Scenario: Reject a mismatched or unsupported continuation
- **WHEN** continuation provider identity, format version, response reference, or persisted schema version is invalid or unsupported
- **THEN** Figura rejects the transition or Run read with a bounded error and does not synthesize or substitute continuation data

#### Scenario: Response has no continuation
- **WHEN** a valid provider response has no continuation payload
- **THEN** Figura stores no continuation payload and the model response has no continuation reference

### Requirement: Continuations are retained for the Run lifecycle and recoverable
Figura SHALL retain a committed continuation for the lifetime of its Run, including after the continuation has been replayed into a later provider request and after the Run becomes terminal. Trusted internal execution code SHALL be able to read continuation data by its Run and originating response reference after process restart. A read SHALL NOT call a provider or tool, change Run progress, or create a new execution fact.

#### Scenario: Read continuation after restart
- **WHEN** trusted execution code reads a committed Run response with a continuation reference after reopening the store
- **THEN** Figura returns the exact stored provider-scoped payload associated with that response

#### Scenario: Read with a different Run or response reference
- **WHEN** a continuation lookup supplies a Session, Run, or response reference that does not own the payload
- **THEN** Figura fails closed without returning the payload or changing Run state

#### Scenario: Retain continuation after it has been replayed
- **WHEN** a later Provider request has used a continuation from an earlier committed response
- **THEN** Figura retains the original payload with that Run and does not consume or delete it

### Requirement: Continuation payloads are bounded and private
Figura SHALL reject a continuation whose UTF-8 encoded payload exceeds 512 KiB before committing any part of the model-response transition. Figura SHALL NOT truncate continuation data. Continuation payloads and references SHALL be omitted from public Run summaries, lifecycle events, ordinary logs, traces, and user-facing error messages; only trusted internal history reconstruction may read the payload.

#### Scenario: Continuation exceeds the payload bound
- **WHEN** a provider response contains continuation data larger than 512 KiB when encoded as UTF-8
- **THEN** Figura rejects the complete response transition, retains the prior committed checkpoint, and reports only a bounded safe error

#### Scenario: Project Run state publicly
- **WHEN** Figura serializes a Run summary, lifecycle event, ordinary diagnostic, or user-facing error
- **THEN** it excludes continuation payloads and continuation references

#### Scenario: Reconstruct provider history internally
- **WHEN** trusted execution code assembles the next provider request from committed Run history
- **THEN** it can retrieve and pass the exact continuation payload for the originating assistant response without merging it into assistant text
