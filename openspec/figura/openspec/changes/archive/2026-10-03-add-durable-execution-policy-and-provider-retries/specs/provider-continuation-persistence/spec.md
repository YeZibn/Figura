## MODIFIED Requirements

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
