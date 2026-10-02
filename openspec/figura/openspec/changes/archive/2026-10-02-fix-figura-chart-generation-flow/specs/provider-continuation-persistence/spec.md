## MODIFIED Requirements

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


### Requirement: Continuation payloads are bounded and private
Figura SHALL reject a continuation whose UTF-8 encoded payload exceeds 512 KiB before committing any part of the model-response transition. Figura SHALL NOT truncate continuation data. Explicit DeepSeek null SHALL contain no text bytes; empty strings SHALL remain subject to the same ownership and privacy constraints as nonempty strings. Continuation payloads and references SHALL be omitted from public Run summaries, lifecycle events, ordinary logs, traces, and user-facing error messages; only trusted internal history reconstruction may read the payload.

#### Scenario: Continuation exceeds the payload bound
- **WHEN** a provider response contains continuation data larger than 512 KiB when encoded as UTF-8
- **THEN** Figura rejects the complete response transition, retains the prior committed checkpoint, and reports only a bounded safe error

#### Scenario: Project Run state publicly
- **WHEN** Figura serializes a Run summary, lifecycle event, ordinary diagnostic, or user-facing error
- **THEN** it excludes continuation payloads and continuation references

#### Scenario: Reconstruct provider history internally
- **WHEN** trusted execution code assembles the next provider request from committed Run history
- **THEN** it can retrieve and pass the exact continuation payload for the originating assistant response without merging it into assistant text

## ADDED Requirements

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
