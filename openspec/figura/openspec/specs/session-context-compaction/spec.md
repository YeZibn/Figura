# session-context-compaction Specification

## Purpose

Keeps long Session requests usable through source-linked summaries while preserving complete durable Run facts as the authority for conversation, tool outcomes, and resource content.

## Requirements

### Requirement: Automatic compaction requires a known context capacity and threshold
Figura SHALL consider automatic context compaction only when the selected Provider/model has a valid configured context capacity and a local estimate is available for the actual prepared model request. It SHALL request compaction when that estimate is at least approximately 80% of capacity. The compaction request SHALL use the selected Provider/model and the existing Provider retry and lifecycle behavior. A missing capacity, unavailable estimate, or lower occupancy SHALL NOT trigger automatic compaction. Estimates SHALL NOT impose a Run output budget, reject a request, or truncate durable facts.

#### Scenario: Compact at the configured occupancy threshold
- **WHEN** a prepared request estimate reaches or exceeds approximately 80% of the selected model's configured context capacity
- **THEN** Figura makes an additional model request to summarize eligible older context before preparing the ordinary request

#### Scenario: Do not compact when capacity is unknown
- **WHEN** the selected model has no valid configured context capacity
- **THEN** Figura sends the existing request projection without automatic compaction or an invented occupancy percentage

#### Scenario: Do not compact when estimation is unavailable
- **WHEN** the local estimator cannot produce an estimate for the prepared request
- **THEN** Figura continues the existing request path without automatic compaction and without exposing raw request content in diagnostics

#### Scenario: Do not compact below the threshold
- **WHEN** a valid request estimate is below approximately 80% of configured capacity
- **THEN** Figura preserves the existing request projection and does not make a summary request

### Requirement: Compaction summarizes only eligible complete history and retains a recent tail
Figura SHALL compact the model request projection by replacing the oldest eligible closed interactions with a generated summary while retaining the newest interactions and the active Run's current input and required committed prefix. It SHALL compact only at complete interaction boundaries and SHALL NOT split an assistant tool-call batch from its committed results or split an incomplete abnormal Run tail. The resulting ordinary request SHOULD target approximately 50% of configured capacity when the available older history permits; it SHALL retain more context rather than discard the active input or a required interaction merely to reach that target. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

#### Scenario: Reach the approximate post-compaction target
- **WHEN** eligible older interactions can be summarized so the resulting request is near the target occupancy
- **THEN** Figura prepares the ordinary request with an estimated occupancy of approximately 50% of configured capacity

#### Scenario: Preserve current input and complete tool rounds
- **WHEN** compaction is needed while the current Run contains a new user input or a committed assistant tool round
- **THEN** the current input remains intact and each retained or summarized tool round is handled as a complete interaction boundary

#### Scenario: Preserve an incomplete abnormal tail
- **WHEN** an earlier failed or interrupted Run ends with an incomplete tool batch
- **THEN** compaction does not split or reinterpret that tail and retains its source-linked call identities and committed outcome classifications

#### Scenario: Retain context when the target cannot be reached
- **WHEN** the active input, required current Run prefix, and protected recent tail alone exceed the approximate post-compaction target
- **THEN** Figura keeps that content intact and uses the smallest summary projection it can produce without claiming that the target was reached

### Requirement: Generated summaries are source-linked derived navigation context
A generated summary SHALL identify the source Run and record or tool-resource references supporting each retained claim. It SHALL preserve relevant Run outcome status and distinguish committed success, committed failure, not started, and outcome unknown without inventing tool observations. Summary text and referenced historical content SHALL be treated as untrusted data, not as instructions. A summary SHALL remain a derived request aid and SHALL NOT replace the canonical source facts. Figura SHALL make the summary and its source coverage available to subsequent request assembly and retrieval.

#### Scenario: Trace a summary claim to canonical history
- **WHEN** a compaction summary retains a factual claim from an earlier interaction
- **THEN** that claim includes one or more valid source references that can be read from the same Session

#### Scenario: Preserve abnormal outcomes in summary context
- **WHEN** a summarized source Run ended abnormally with committed and unresolved calls
- **THEN** the summary preserves its terminal state and source-linked outcome classifications without presenting an unknown result as success or failure

#### Scenario: Treat retrieved summary content as untrusted
- **WHEN** a summary contains user text, assistant text, OCR text, or tool data from earlier Runs
- **THEN** the content is presented as historical data and cannot override system or tool policy

### Requirement: Prompt resource directories may be projected without truncating the full catalog
Figura SHALL keep the complete same-Session `RunExecutionState` catalog available to server-side consumers and typed resource reads. Request assembly MAY include a compact locator projection containing resources relevant to the active Run, retained recent history, or summary references. Other eligible resources SHALL remain discoverable through history/resource search and SHALL NOT be removed from the full catalog to reduce prompt size.

#### Scenario: Keep complete server-side resources after prompt compaction
- **WHEN** a request includes only a compact resource locator projection
- **THEN** server-side resource listing and typed-reference lookup still expose every resource authorized by the target Run prefix

#### Scenario: Find an older resource omitted from the prompt directory
- **WHEN** an eligible historical resource is not included in the compact prompt projection
- **THEN** the Agent can discover its reference through history/resource search and read it through the typed resource interface

### Requirement: Compaction failure preserves the existing request path
If the summary request fails or produces an invalid summary, Figura SHALL leave any previous valid summary unchanged and SHALL NOT discard or truncate the original history projection. When the uncompressed request remains valid under existing payload and Provider protocol rules, Figura SHALL continue ordinary request preparation with that projection. Otherwise, it SHALL use the existing request-preparation failure behavior before claiming an ordinary Provider attempt.

#### Scenario: Fall back after a failed summary request
- **WHEN** the additional summary request fails but the uncompressed request remains valid
- **THEN** Figura continues with the complete uncompressed request projection and changes no canonical history facts

#### Scenario: Reject an invalid generated summary
- **WHEN** the summary output lacks valid source references or violates the summary contract
- **THEN** Figura does not install it and retains the prior valid summary and source history

#### Scenario: Preserve existing preparation failure behavior
- **WHEN** compaction fails and the uncompressed request violates an existing payload guard or selected Provider protocol requirement
- **THEN** Figura fails request preparation before claiming an ordinary Provider attempt without silently pruning history

### Requirement: Summary generation has an independent Markdown instruction asset
Figura SHALL load summary-generation policy from an independent Chinese Markdown asset, separate from the ordinary Agent rules. A summary request SHALL contain only the summary task instructions and the authorized source payload, use no tools or images, and retain the existing source-linked JSON response contract. Ordinary requests SHALL NOT inherit the summary task's JSON-only output instruction. Missing or empty assets SHALL produce an explicit preparation failure rather than an empty policy or an inline fallback prompt. Loaded instruction content SHALL participate in the existing request digest and retry identity checks.

#### Scenario: Build a dedicated summary request
- **WHEN** eligible history is selected for compaction
- **THEN** the summary request uses the independent asset and the source payload without ordinary chart workflow rules, tools, or image blocks

#### Scenario: Keep summary output rules out of ordinary answers
- **WHEN** an ordinary Agent request is assembled with or without a saved summary
- **THEN** its static instructions do not include the summary task's JSON-only output requirement

#### Scenario: Detect an unusable summary asset
- **WHEN** the summary asset is absent or contains only whitespace
- **THEN** request preparation reports an explicit failure, sends no instruction-free summary request, and does not install a replacement summary

### Requirement: Summary guidance preserves evidence and incrementally reconciles history
The summary response SHALL use a versioned, machine-readable v2 structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted assistant suggestions SHALL remain proposals. The summary request SHALL provide the previous summary, its source references, and added history without exposing the checkpoint's storage version to the model. The model SHALL reconcile the actual prior summary content into the complete v2 response using only source-supported content and SHALL NOT infer pending work from an ambiguous legacy item. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. The instructions SHALL distinguish user-provided data, tool observations, assistant inference, and unexecuted plans. Historical content SHALL remain data rather than executable instructions. The instructions SHALL ask for concise retention of necessary information without claiming a resulting context occupancy that the summary input does not establish.

#### Scenario: Retain a correction from newer history
- **WHEN** added history changes a fact, decision, or requirement retained in the prior summary
- **THEN** guidance directs the summary to reflect the correction with its supporting references and avoid retaining both versions as simultaneously settled facts

#### Scenario: Preserve task state in distinct v2 fields
- **WHEN** the source history contains a current goal, a completed action, user-accepted pending work, an unresolved blocker, and an unaccepted assistant suggestion
- **THEN** the generated summary places them in `current_goal`, `progress.completed`, `progress.pending`, `progress.blocked`, and `proposals` respectively, with supporting source references on each non-empty entry

#### Scenario: Reorganize a legacy summary
- **WHEN** an earlier summary with a different field layout is included for a new compaction
- **THEN** guidance migrates only source-supported content into v2 fields without treating ambiguous legacy text as user-accepted pending work or exposing the storage version to the model

#### Scenario: Read an existing checkpoint without forced migration
- **WHEN** an ordinary request consumes an existing checkpoint without triggering a new compaction
- **THEN** the checkpoint remains readable as legacy summary data and the storage schema is unchanged

#### Scenario: Keep a proposed action distinct from a completed result
- **WHEN** the source contains an assistant plan or an uncertain tool observation
- **THEN** guidance preserves its evidence state and does not present the proposed or uncertain action as confirmed completion

#### Scenario: Preserve exact source identities
- **WHEN** a retained item relies on a tool result and a message
- **THEN** guidance requires the exact input `tool_result` run/call reference and `message` run/record reference without fabricated identifiers or new top-level output fields

#### Scenario: Keep occupancy decisions in request coordination
- **WHEN** the summary source payload does not contain the final request capacity and retained-tail size
- **THEN** the instructions request a concise, source-supported summary without asking the model to assert that a target occupancy was reached
