## MODIFIED Requirements

### Requirement: Compaction operations freeze their budgets and exact coverage for recovery
When Figura starts a compaction operation, it SHALL durably bind the selected context capacity, both derived history budgets, summary contract version, target Run's committed base record/tool sequences, and exact Run/record/tool coverage coordinates. Coverage MAY end within the active target Run but SHALL NOT extend beyond its frozen committed base prefix. Once the summary request is prepared, Figura SHALL create a canonical Provider logical request record that freezes the rendered summary instruction and digest, prepared request fingerprint, Provider/model, stream contract, timeout and retry policy identities, and context estimate. The compaction operation SHALL reference that logical request rather than maintain a second Provider binding or attempt counter. A retry or restart SHALL reconstruct the same source slice and request identity even if Provider capacity configuration, Run status, or prompt assets change afterward. The checkpoint SHALL advance only after a valid terminal stream, summary validation, and the existing expected-revision compare-and-swap succeed. The existing valid checkpoint SHALL remain unchanged when preparation, dispatch, or validation fails.

#### Scenario: Resume after capacity configuration changes
- **WHEN** a compaction operation is interrupted and the selected Provider capacity changes before restart
- **THEN** Figura resumes with the operation's persisted capacity, budgets, cutoff, base prefix, and canonical Provider request record rather than selecting a new slice

#### Scenario: Resume an active-Run summary after interruption
- **WHEN** an active-Run compaction operation is resumed after process restart
- **THEN** Figura reconstructs only the source interactions within the persisted committed prefix, even if newer Run facts are now available

#### Scenario: Preserve the previous checkpoint after a failed replacement
- **WHEN** a summary attempt fails, is invalid, or loses its checkpoint compare-and-swap
- **THEN** the previous checkpoint remains authoritative and the current request uses the existing safe fallback behavior

#### Scenario: Apply a checkpoint that ends inside the active Run
- **WHEN** a valid checkpoint covers a committed prefix of the still-running target Run
- **THEN** later requests in that Run keep its original input, use the summary for covered process, and project only complete process interactions after the cutoff as raw history

## ADDED Requirements

### Requirement: Summary generation uses the canonical streaming Provider path
Figura SHALL dispatch every compaction summary through the same streaming transport, timeout observation, cancellation, retry coordinator, and Provider attempt ledger used by ordinary Agent requests. The summary consumer SHALL assemble the complete stream privately, validate its response contract and source references, and install a checkpoint only after terminal completion. Partial summary text SHALL NOT be exposed as an assistant answer or replace any existing checkpoint.

#### Scenario: Receive a complete summary stream
- **WHEN** a summary request emits a valid terminal stream and the summary passes validation
- **THEN** Figura installs the summary using the operation's frozen coverage and checkpoint revision

#### Scenario: Interrupt summary generation
- **WHEN** a summary stream fails or is cancelled before a valid terminal event
- **THEN** Figura leaves the prior checkpoint unchanged and applies the shared Provider retry or safe fallback behavior
