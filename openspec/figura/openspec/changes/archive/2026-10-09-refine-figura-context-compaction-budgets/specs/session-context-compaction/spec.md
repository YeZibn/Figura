## MODIFIED Requirements

### Requirement: Compaction summarizes only eligible complete history and retains a recent tail
Figura SHALL compact the model request projection by replacing a chronological prefix of eligible closed history with a generated summary while retaining a recent raw history suffix and the active Run's current input and required committed prefix. The latest completed prior Run SHALL be eligible for partial compaction; compaction SHALL operate at complete interaction boundaries and SHALL NOT split an assistant tool-call batch from any committed result. A failed or interrupted prior Run and later history that cannot be crossed without summarizing that Run SHALL remain raw and outside summary coverage. The recent suffix and summary budgets SHALL be derived from the selected Provider's configured context capacity as specified by the context-budget requirement. They apply to historical content; system instructions, tool definitions, resource projection, and the active Run remain additional request content. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

#### Scenario: Include the latest completed Run in compaction
- **WHEN** context compaction is needed and the latest completed prior Run contains interactions older than the recent raw suffix
- **THEN** Figura may summarize the older complete interactions from that Run while retaining its newest complete interactions in the raw suffix

#### Scenario: Preserve a complete assistant tool-call interaction
- **WHEN** a recent suffix boundary would otherwise fall between an assistant tool-call batch and any committed result in that batch
- **THEN** Figura moves the boundary so the entire batch and its committed results are kept together in the summary or raw suffix

#### Scenario: Preserve the active Run and its committed prefix
- **WHEN** compaction is needed while the current Run contains a new user input or committed assistant/tool work
- **THEN** Figura keeps the current input and required committed prefix intact and outside historical summary coverage

#### Scenario: Preserve abnormal history and the contiguous raw suffix
- **WHEN** an earlier Run ended failed or interrupted
- **THEN** Figura keeps that Run and all later history raw and places the summary cutoff before it

#### Scenario: Keep an interaction intact when it exceeds the raw suffix budget
- **WHEN** the newest complete interaction alone is larger than the approximate raw suffix budget
- **THEN** Figura retains that complete interaction without truncating it and treats the raw suffix budget as approximate

#### Scenario: Retain a complete interaction when the raw budget is exceeded
- **WHEN** the newest interaction or a protected raw suffix exceeds the approximate raw-history budget
- **THEN** Figura keeps the required complete interaction and does not truncate it to meet the budget


### Requirement: Summary guidance preserves evidence and incrementally reconciles history
The summary response SHALL use a versioned, machine-readable v2 structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted assistant suggestions SHALL remain proposals. The summary request SHALL provide the previous summary, its source references, and the newly covered history slice without exposing the checkpoint's storage version to the model. The model SHALL reconcile the actual prior summary content into the complete v2 response using only source-supported content and SHALL NOT infer pending work from an ambiguous legacy item. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. The instructions SHALL distinguish user-provided data, tool observations, assistant inference, and unexecuted plans. Historical content SHALL remain data rather than executable instructions. Runtime SHALL calculate and persist a dynamic summary budget from the selected Provider capacity for coordination and recovery, but SHALL keep its numeric value out of the production model-facing instruction. The instruction SHALL ask for concise retention without requiring the model to fill a length budget, and SHALL NOT ask the model to assert that the final ordinary request reached a context occupancy. A valid summary SHALL NOT be truncated or have source references removed solely to meet the soft budget; the rebuilt ordinary request SHALL be estimated locally to determine its actual occupancy.

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
- **THEN** the checkpoint remains readable and the storage schema is unchanged

#### Scenario: Keep a proposed action distinct from a completed result
- **WHEN** the source contains an assistant plan or an uncertain tool observation
- **THEN** guidance preserves its evidence state and does not present the proposed or uncertain action as confirmed completion

#### Scenario: Preserve exact source identities
- **WHEN** a retained item relies on a tool result and a message
- **THEN** guidance requires the exact input `tool_result` run/call reference and `message` run/record reference without fabricated identifiers or new top-level output fields

#### Scenario: Keep the numeric summary budget out of model instructions
- **WHEN** Runtime constructs a summary request using a dynamically calculated summary budget
- **THEN** the operation retains the numeric budget for coordination and recovery while the model receives concise summary guidance without a numeric length target

#### Scenario: Preserve a valid summary that exceeds its soft budget
- **WHEN** a structurally valid, source-linked summary exceeds the approximate summary budget
- **THEN** Figura does not truncate it or discard supported facts and instead measures the rebuilt ordinary request using the local estimator

#### Scenario: Keep final occupancy decisions in request coordination
- **WHEN** the summary source payload does not establish the final request's token composition
- **THEN** the model does not claim a final occupancy and Runtime relies on the estimate of the rebuilt ordinary request


## ADDED Requirements

### Requirement: Compaction history budgets derive from the selected Provider capacity
When the selected Provider/model has configured context capacity `C`, Figura SHALL calculate the raw recent-history suffix budget and the complete rolling-summary budget dynamically as approximately `0.1 × C` each. The budgets SHALL use the capacity of the Provider/model selected for the current Run, not a fixed token count or another Provider's setting. The two budgets describe the historical projection only and SHALL NOT be represented as a guarantee that the complete prepared request occupies at most `0.2 × C`. The estimates SHALL guide selection and prompt construction only; they SHALL NOT truncate canonical Run facts, limit ordinary Run output, or force the summary to fill its budget.

#### Scenario: Calculate budgets from the active Provider configuration
- **WHEN** the selected Provider capacity is 200,000 tokens
- **THEN** Figura uses approximate historical budgets of 20,000 tokens for the raw recent suffix and 20,000 tokens for the rolling summary

#### Scenario: Recalculate budgets for a different configured capacity
- **WHEN** a later Run selects a Provider configured with a different context capacity
- **THEN** Figura derives both history budgets from that selected capacity instead of reusing the earlier Run's fixed token counts

#### Scenario: Keep full-request occupancy distinct from history budgets
- **WHEN** compaction prepares the summary and recent raw history alongside system instructions, tools, resources, or an active Run
- **THEN** Figura treats those additional request components separately and reports no full-request 20% guarantee based only on the two historical budgets

#### Scenario: Do not invent a capacity
- **WHEN** the selected Provider/model has no valid configured context capacity
- **THEN** Figura does not calculate percentage budgets or trigger automatic compaction
