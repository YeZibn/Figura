# provider-continuation-persistence Specification

## Purpose

Persists provider-private continuation payloads with the exact Figura Run model response that produced them, so trusted execution code can reconstruct provider history after restart without exposing reasoning data through public Run projections.

## Requirements

### Requirement: Continuations are scoped to one committed model response
When a normalized provider response contains continuation data, Figura SHALL persist one private continuation payload linked to the same Run, model-response record, provider, and continuation format version. The model response SHALL contain an opaque optional continuation reference; a non-null reference SHALL resolve to exactly one payload for that response. A response without continuation data SHALL have no continuation reference or payload. For DeepSeek, an actually returned `reasoning_content` field containing a string, including an empty string, or explicit null SHALL constitute continuation data and SHALL retain its exact value and JSON type. A missing field SHALL remain absent and SHALL NOT be synthesized from an SDK default, null, or empty string. Other value types SHALL be rejected. Other Providers SHALL retain their existing nonempty continuation rules. Non-streaming and streaming normalization SHALL preserve these distinctions; streamed string fragments SHALL concatenate in order, null fragments SHALL contribute no text, an explicitly returned null-only field SHALL remain null, and no returned field SHALL mean no continuation.

#### Scenario: Commit a provider continuation
- **WHEN** a valid provider response contains nonempty continuation data for the Run's selected provider and a supported format version
- **THEN** Figura stores the payload privately and links its opaque reference to that response record

#### Scenario: Reject a mismatched or unsupported continuation
- **WHEN** continuation provider identity, format version, response reference, or persisted schema version is invalid or unsupported
- **THEN** Figura rejects the transition or Run read with a bounded error and does not synthesize or substitute continuation data

#### Scenario: Response has no continuation
- **WHEN** a valid provider response has no continuation payload
- **THEN** Figura stores no continuation payload and the model response has no continuation reference

#### Scenario: Preserve explicitly empty DeepSeek continuation
- **WHEN** a DeepSeek response actually returns `reasoning_content` as an empty string or explicit null
- **THEN** Figura commits a matching private continuation and response reference atomically
- **AND** trusted same-Session request reconstruction after restart replays the exact value and JSON type for that assistant response, including across Runs

#### Scenario: Keep missing reasoning absent
- **WHEN** a DeepSeek response does not actually return a reasoning field, including when an SDK object exposes an unset default
- **THEN** Figura stores no continuation for that response
- **AND** a later request requiring that continuation is rejected locally without inventing reasoning

#### Scenario: Normalize streamed empty and null reasoning
- **WHEN** DeepSeek stream events explicitly return null-only reasoning or one or more string fragments including empty strings
- **THEN** null-only reasoning is retained as null and returned string fragments are concatenated in order
- **AND** malformed non-string non-null values are rejected rather than coerced

#### Scenario: Preserve other Provider behavior
- **WHEN** Qwen or MiMo returns no nonempty reasoning continuation
- **THEN** Figura retains the existing normalization and validation behavior for that Provider

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
Figura SHALL reject a continuation whose complete envelope or complete response transition exceeds the shared execution-payload guard before committing any part of the model-response transition. Figura SHALL NOT truncate continuation data. Explicit DeepSeek null SHALL contain no text bytes; empty strings SHALL remain subject to the same ownership and privacy constraints as nonempty strings. Continuation payloads and references SHALL be omitted from public Run summaries, lifecycle events, ordinary logs, traces, and user-facing error messages; only trusted internal history reconstruction may read the payload.

#### Scenario: Continuation exceeds the payload bound
- **WHEN** a provider response contains continuation data whose complete UTF-8 JSON envelope or complete response transition exceeds the shared payload guard
- **THEN** Figura rejects the complete response transition, retains the prior committed checkpoint, and reports only a bounded safe error

#### Scenario: Project Run state publicly
- **WHEN** Figura serializes a Run summary, lifecycle event, ordinary diagnostic, or user-facing error
- **THEN** it excludes continuation payloads and continuation references

#### Scenario: Reconstruct provider history internally
- **WHEN** trusted execution code assembles the next provider request from committed Run history
- **THEN** it can retrieve and pass the exact continuation payload for the originating assistant response without merging it into assistant text

#### Scenario: Accept a continuation above the previous micro limit
- **WHEN** a valid continuation exceeds 512 KiB but fits the shared complete-envelope and response-transition guards
- **THEN** Figura commits it unchanged while preserving exact source identity, format, empty/null distinctions and privacy

### Requirement: Continuation value-domain migration preserves committed history
When upgrading a supported existing store to support explicit DeepSeek empty and null continuations, Figura SHALL retain existing continuation values, identities, response links, immutable facts, checkpoints, and terminal outcomes. Migration SHALL remain atomic and SHALL preserve referential integrity, continuation immutability, and authorized Session aggregate deletion. Figura SHALL NOT infer a missing historical payload or rewrite terminal Runs to repair unavailable reasoning.

#### Scenario: Upgrade existing continuation facts
- **WHEN** a supported existing database with committed nonempty continuations is upgraded
- **THEN** all existing values and references remain unchanged and readable
- **AND** newly committed explicit DeepSeek empty and null values remain distinguishable after restart

#### Scenario: Roll back unsuccessful migration
- **WHEN** the continuation migration fails before transaction commit
- **THEN** existing facts and schema version remain unchanged

#### Scenario: Preserve unavailable historical continuation
- **WHEN** a stored assistant response has no continuation reference before migration
- **THEN** migration leaves that response without a continuation reference or fabricated payload
