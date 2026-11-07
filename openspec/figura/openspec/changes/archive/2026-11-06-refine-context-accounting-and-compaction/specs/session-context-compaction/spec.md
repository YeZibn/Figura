## MODIFIED Requirements

### Requirement: Automatic compaction requires a known context capacity and threshold
Figura SHALL consider automatic context compaction only when the selected Provider/model has a valid configured context capacity and a local estimate is available for the actual prepared model request. At approximately 80% of capacity it SHALL evaluate directory reduction and eligible history compaction. It SHALL issue a new summary only when newly coverable history can advance exact coverage; high occupancy alone SHALL NOT repeatedly summarize the same prefix. The compaction request SHALL use the selected Provider/model and the existing Provider retry and lifecycle behavior. A missing capacity, unavailable estimate, or lower occupancy SHALL NOT trigger automatic compaction. Estimates SHALL NOT impose a Run output budget, reject a request, or truncate durable facts.

#### Scenario: Compact at the configured occupancy threshold
- **WHEN** a prepared request estimate reaches or exceeds approximately 80% of the selected model's configured context capacity
- **THEN** Figura evaluates reducible directory content and, when eligible new coverage exists, makes an additional summary request before ordinary preparation

#### Scenario: Do not compact when capacity is unknown
- **WHEN** the selected model has no valid configured context capacity
- **THEN** Figura sends the existing request projection without automatic compaction or an invented occupancy percentage

#### Scenario: Do not compact when estimation is unavailable
- **WHEN** the local estimator cannot produce an estimate for the prepared request
- **THEN** Figura continues the existing request path without automatic compaction and without exposing raw request content in diagnostics

#### Scenario: Do not compact below the threshold
- **WHEN** a valid request estimate is below approximately 80% of configured capacity
- **THEN** Figura preserves the existing request projection and does not make a summary request

### Requirement: Compaction history budgets derive from the selected Provider capacity
For a valid configured context capacity `C`, Figura SHALL use `floor(C / 10)` tokens each as the preferred raw-history and summary targets. It SHALL shrink the effective soft targets when necessary based on the remaining space after necessary non-history input and selected directory content within the approximately 80% input target. The operation SHALL freeze both effective targets and their accounting basis. The raw-process budget SHALL cover retained Assistant messages, tool calls, tool results, and the per-Run input locator needed to interpret them, including eligible committed interactions from the active Run. It SHALL include uncovered historical user input once with its source locator. The current Run input SHALL remain separately complete. Prior inputs already represented by input-aware summary coverage SHALL NOT be duplicated. The summary target SHALL guide the approximate token length of the complete summary JSON; it SHALL NOT be a completion-token cap, hard request limit, Run output limit, or truncation rule. Historical user-input text, the active Run's complete input, instructions, tool definitions, resource projection, and other request content SHALL be included in the actual prepared-request estimate. Missing or invalid capacity SHALL disable automatic compaction. A valid summary SHALL NOT be padded, truncated, or rejected by length.

#### Scenario: Calculate budgets from the active Provider configuration
- **WHEN** the selected model has a configured capacity of 200,000 tokens
- **THEN** the raw recent-process budget and the summary target have preferred values of 20,000 estimated tokens each when remaining space permits

#### Scenario: Recalculate budgets for a different configured capacity
- **WHEN** a later Run selects a Provider configured with a different context capacity
- **THEN** Figura derives both values from that selected capacity instead of reusing earlier token counts

#### Scenario: Scale budgets for a larger model capacity
- **WHEN** the selected model has a configured capacity of 1,000,000 tokens
- **THEN** the raw recent-process budget and summary target have preferred values of 100,000 estimated tokens each when remaining space permits

#### Scenario: Include active committed process in the raw-history budget
- **WHEN** compaction is considered during a running Run with committed complete interactions
- **THEN** those interactions participate in the same capacity-derived, remaining-space-adjusted raw-tail selection as eligible prior Run process, while the active input text remains separately preserved

#### Scenario: Keep full-request occupancy distinct from history budgets
- **WHEN** compaction prepares a summary and recent raw history alongside current and uncovered historical user inputs, system instructions, tools, resources, or other active request content
- **THEN** Figura includes all those components in the actual request estimate and makes no full-request 20% occupancy guarantee based only on the two history budgets

#### Scenario: Do not invent a capacity
- **WHEN** capacity is absent, non-positive, or not an integer
- **THEN** Figura does not calculate history budgets or automatically compact the request

#### Scenario: Provide the dynamic summary target in the prompt
- **WHEN** Figura creates a new compaction operation for a configured capacity of 200,000 tokens
- **THEN** the summary instruction tells the model that the complete summary JSON has the frozen effective approximate target, preferred at 20,000 tokens and reduced when remaining space requires while allowing shorter or longer valid output

#### Scenario: Keep the target approximate
- **WHEN** the generated summary is shorter or longer than the estimated summary budget
- **THEN** Figura preserves a valid source-linked summary as generated and does not pad, truncate, or reject it solely because of length

### Requirement: Compaction summarizes eligible complete history and retains a recent tail
Figura SHALL compact eligible committed process messages across prior Runs and the active Run by replacing a chronological prefix with a generated summary while retaining a recent raw process suffix and the active Run's exact current input. A prior Run's complete input SHALL be projected once until input-aware summary coverage includes it. Covered prior inputs SHALL be represented by source-linked summary instead of an unconditional full-input section. Legacy process-only checkpoints SHALL NOT authorize omission until their covered inputs have been reconciled into a new input-aware summary. Current input SHALL remain exact even when its process is summarized. The active Run's input SHALL remain its native user message and SHALL NOT be duplicated in the historical-input section. The raw suffix SHALL contain a source locator for each corresponding Run input rather than duplicating input text. The latest completed prior Run SHALL remain eligible for partial compaction. The active Run SHALL be eligible for compaction only through its last committed record/tool prefix at the time the compaction operation is bound. Compaction SHALL operate at complete interaction boundaries and SHALL NOT split an Assistant tool-call batch from any committed result. In-flight Provider work, uncommitted records, and incomplete tool-call batches SHALL remain raw and outside summary coverage. A failed or interrupted prior Run and later process history that cannot be crossed without newly summarizing that Run SHALL remain raw. If a Run becomes failed or interrupted after a committed prefix was already covered, Figura SHALL preserve that existing summary coverage and keep the terminal outcome and uncovered suffix raw. The raw-process budget and summary target SHALL be derived from the selected Provider's configured context capacity as specified by the compaction history budget requirement. New input-aware coverage SHALL advance over newly covered complete interactions or previously uncovered eligible input records. Legacy input reconciliation SHALL use a new versioned operation without rewriting old checkpoints or frozen requests. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

The latest fully committed visual tool interaction awaiting ordinary model observation SHALL remain in the raw suffix with its assistant call batch, all results and attachment descriptions. Protected abnormal history or a spent raw budget SHALL NOT allow that interaction to enter the summary; the target is soft. The active Run's earlier complete interactions remain eligible. Summary sources SHALL include canonical business observations and attachment references/provenance without image bytes, generated hints or request-only images_loaded markers. A summary request SHALL NOT consume visual feedback. The next ordinary request and its retries SHALL attach the selected saved images only inside their retained owning tool results.

#### Scenario: Project prior inputs according to input-aware coverage
- **WHEN** prior Runs have user inputs before or after the process-summary cutoff
- **THEN** covered prior inputs use the source-linked summary and uncovered inputs retain exact text, ordered attachment IDs and their input-message source reference

#### Scenario: Preserve duplicate and empty user inputs as separate source records
- **WHEN** distinct prior Runs contain identical text or an empty text input with attachments
- **THEN** Figura retains separate canonical source identities; uncovered inputs remain distinct raw entries, and summarized inputs preserve exact source references and relevant attachment identities

#### Scenario: Avoid duplicating historical input text in the raw message tail
- **WHEN** a prior Run's process interaction remains in the raw suffix
- **THEN** the raw projection includes an exact input-message locator and includes the input body once only if that prior input is not covered by an input-aware summary

#### Scenario: Keep the current input as the native user message
- **WHEN** an ordinary request is assembled for a running Run
- **THEN** the current Run's complete input remains a native user message and is not duplicated in the historical-input section

#### Scenario: Include the latest completed Run in compaction
- **WHEN** context compaction is needed and the latest completed prior Run contains interactions older than the recent raw suffix
- **THEN** Figura may summarize the older complete interactions from that Run while retaining its newest complete interactions in the raw suffix

#### Scenario: Include the active Run's committed interactions in compaction
- **WHEN** context compaction is needed during a running Run and its committed process contains complete interactions older than the selected raw suffix
- **THEN** Figura may summarize those older complete interactions and retain the active Run's newest complete interactions raw

#### Scenario: Supply the active Run input as summary context
- **WHEN** a summary covers committed process from the active Run
- **THEN** the summary request includes that Run's complete input, attachment IDs, and input-message reference separately from newly covered process messages, while the ordinary request retains the input as its native user message

#### Scenario: Preserve the active Run's unfinished state in its summary
- **WHEN** a summary covers process from a Run that is still running
- **THEN** the summary preserves source-supported progress without presenting the Run or its unfinished goal as completed solely because the covered prefix contains successful actions

#### Scenario: Bound active-Run coverage to the frozen committed prefix
- **WHEN** an active-Run compaction operation is created
- **THEN** its summary source contains no record or tool result beyond the operation's captured committed record/tool sequences

#### Scenario: Preserve a complete assistant tool-call interaction
- **WHEN** a recent suffix boundary would otherwise fall between an assistant tool-call batch and any committed result in that batch
- **THEN** Figura moves the boundary so the entire batch and its committed results are kept together in the summary or raw suffix

#### Scenario: Keep in-flight and incomplete work raw
- **WHEN** a Provider action is unresolved, a record is not committed, or a tool-call batch has incomplete results
- **THEN** Figura keeps that work outside summary coverage until it becomes a committed complete interaction

#### Scenario: Preserve abnormal history that has not already been covered
- **WHEN** a prior Run ended failed or interrupted and its process has not previously entered a summary
- **THEN** Figura keeps that Run and later process history raw and places new summary coverage before it

#### Scenario: Preserve prior coverage if the active Run later becomes abnormal
- **WHEN** a Run becomes failed or interrupted after an earlier committed prefix from that Run was summarized
- **THEN** Figura keeps the existing checkpoint, refreshes the projected Run outcome from canonical status, preserves the terminal outcome and uncovered suffix raw, and does not claim the Run completed successfully

#### Scenario: Keep an interaction intact when it exceeds the raw suffix budget
- **WHEN** the newest complete interaction alone is larger than the approximate raw suffix budget
- **THEN** Figura retains that complete interaction without truncating it and treats the raw suffix budget as approximate

#### Scenario: Retain a complete interaction when the raw budget is exceeded
- **WHEN** the newest interaction or a protected raw suffix exceeds the approximate raw-history budget
- **THEN** Figura keeps the required complete interaction and does not truncate it to meet the budget

#### Scenario: Continue from a checkpoint inside a Run
- **WHEN** a later compaction extends a checkpoint whose coverage ends within either a completed Run or the active Run's committed prefix
- **THEN** its summary request includes the previous summary and source references plus only newly covered complete process interactions, with each source Run's original input supplied separately as context

#### Scenario: Preserve historical inputs when the full request is too large
- **WHEN** protected historical inputs or the active input cause the prepared request to exceed the selected Provider's usable capacity
- **THEN** Figura does not silently omit or truncate inputs and follows the existing request-preparation failure behavior

#### Scenario: Preserve canonical history facts
- **WHEN** compaction succeeds or falls back
- **THEN** all original Run records, tool calls, tool results, and resource data remain available unchanged

#### Scenario: Protect a visual batch when abnormal history already exhausts the raw budget
- **WHEN** protected abnormal history consumes the raw-history target and the newest complete tool batch has images awaiting ordinary model observation
- **THEN** Figura retains that entire newest batch raw, can exceed the soft target and does not leave an image separated from its native tool result

#### Scenario: Do not turn an image hint into a summary fact
- **WHEN** eligible history contains image attachments and their request-time observation hints
- **THEN** the summary input uses business observations and original attachment references/provenance, without treating hints as user requirements or evidence of a visual finding

### Requirement: Compaction operations freeze their budgets and exact coverage for recovery
When Figura starts a compaction operation, it SHALL durably bind the selected context capacity, both effective history targets, their accounting basis, input-coverage and projection policy versions, summary contract version, target Run's committed base record/tool sequences, and exact Run/record/tool coverage coordinates. Coverage MAY end within the active target Run but SHALL NOT extend beyond its frozen committed base prefix. Once the summary request is prepared, Figura SHALL create a canonical Provider logical request record that freezes the rendered summary instruction and digest, prepared request fingerprint, Provider/model, stream contract, timeout and retry policy identities, and context estimate. The compaction operation SHALL reference that logical request rather than maintain a second Provider binding or attempt counter. A retry or restart SHALL reconstruct the same source slice and request identity even if Provider capacity configuration, Run status, or prompt assets change afterward. The checkpoint SHALL advance only after a valid terminal stream, summary validation, and the existing expected-revision compare-and-swap succeed. The existing valid checkpoint SHALL remain unchanged when preparation, dispatch, or validation fails.

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

#### Scenario: Preserve a legacy frozen projection
- **WHEN** recovery finds a request frozen under the complete-historical-input policy
- **THEN** Figura reconstructs the original policy and fingerprint or uses existing safe failure/fallback behavior without silently rebinding the request


### Requirement: Preflight the summary request and re-estimate the ordinary request
Before dispatching a summary request, Figura SHALL prepare the actual Provider payload, including each selected source Run's original input as a separate object containing its text, attachment IDs, and input-message reference, and require an available local estimate such that estimated input plus configured maximum completion tokens does not exceed the operation's frozen capacity. Newly covered process messages SHALL exclude UserMessage bodies because their inputs are supplied separately. If the summary request cannot be safely prepared within that capacity, Figura SHALL dispatch no summary request, preserve the prior checkpoint, and follow the existing full-history fallback path. After successful compaction, Figura SHALL rebuild and locally estimate the ordinary request, including uncovered historical inputs, exact current input and the selected directory, using the new checkpoint while keeping the existing approximately 80% automatic trigger. If the ordinary request cannot fit, Figura SHALL NOT silently omit or truncate historical inputs. History budgets SHALL NOT be described as the resulting full-request occupancy.

#### Scenario: Reject a summary request that exceeds the frozen capacity
- **WHEN** the prepared summary payload plus configured maximum completion tokens exceeds the operation's capacity, or the estimate is unavailable
- **THEN** Figura dispatches no summary request, leaves the previous checkpoint unchanged, and safely falls back to the ordinary history projection

#### Scenario: Re-estimate after installing a summary
- **WHEN** a valid summary checkpoint is installed
- **THEN** Figura rebuilds and estimates the ordinary request before claiming its Provider attempt

#### Scenario: Do not claim the full request fits within the history budgets
- **WHEN** raw history and summary budgets each use ten percent of configured context capacity
- **THEN** diagnostics and documentation describe them as historical-projection budgets and do not claim the full ordinary request uses only the remaining eighty percent

#### Scenario: Avoid ineffective repeated compaction
- **WHEN** the rebuilt request remains above the trigger without newly coverable history
- **THEN** Figura retains protected content and follows existing preparation rules without another summary of the same prefix


### Requirement: Prompt resource directories may be projected without truncating the full catalog
Figura SHALL keep the complete same-Session `RunExecutionState` catalog available to server-side consumers and typed resource reads. Request assembly SHALL use a deterministic soft-budgeted locator projection. It SHALL prioritize current input resources, the latest retained tool interaction, resources explicitly referenced by retained calls, and their directly recorded source relationships. Other active-Run and recent-history resources SHALL be admitted within remaining space in stable recency order. Exact summary references SHALL remain usable without requiring duplicate expanded directory entries. Exact mandatory locators SHALL NOT be truncated to satisfy a soft budget. Filtering SHALL also operate before a summary exists when capacity accounting is available; without capacity or estimates the existing reference-based projection SHALL remain available. Other eligible resources SHALL remain discoverable through history/resource search and SHALL NOT be removed from the full catalog to reduce prompt size.

#### Scenario: Keep complete server-side resources after prompt compaction
- **WHEN** a request includes only a compact resource locator projection
- **THEN** server-side resource listing and typed-reference lookup still expose every resource authorized by the target Run prefix

#### Scenario: Find an older resource omitted from the prompt directory
- **WHEN** an eligible historical resource is not included in the compact prompt projection
- **THEN** the Agent can discover its reference through history/resource search and read it through the typed resource interface

#### Scenario: Filter before the first summary
- **WHEN** optional directory metadata exceeds available space without a summary checkpoint
- **THEN** Figura may omit optional entries while keeping required exact locators and the full authorized catalog

#### Scenario: Mandatory locators exceed the soft target
- **WHEN** required resource metadata exceeds the directory target
- **THEN** Figura retains exact locators and records unmet soft-target pressure without truncating or fabricating references

#### Scenario: Deterministic resource selection
- **WHEN** facts, policy and frozen request basis are identical
- **THEN** resource selection and ordering are identical without semantic ranking by a model


### Requirement: Summary generation has an independent Markdown instruction asset
Figura SHALL load summary-generation policy from an independent Chinese Markdown asset, separate from the ordinary Agent rules. For each new compaction operation, Runtime SHALL render the selected Provider capacity and the operation's effective approximate complete-summary target derived from capacity and remaining space into that instruction. The instruction SHALL allow shorter or longer valid JSON and SHALL NOT treat the target as a completion-token cap or ask the model to report final ordinary-request occupancy. A summary request SHALL contain only the summary task instructions and the authorized source payload, use no tools or images, and retain the existing source-linked JSON response contract. Ordinary requests SHALL NOT inherit the summary task's JSON-only output instruction. Missing or empty assets SHALL produce an explicit preparation failure rather than an empty policy or an inline fallback prompt. Loaded and rendered instruction content SHALL participate in the existing request digest and retry identity checks.

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
The summary response SHALL retain the existing machine-readable field structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input-message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted Assistant suggestions SHALL remain proposals. The summary request SHALL provide the previous summary, its source references, and only newly covered complete process interactions. Each selected source Run's complete original user input, attachment IDs, and input-message reference SHALL be supplied separately from those process messages. The model SHALL use this input to understand the process slice but SHALL NOT be responsible for preserving the original input verbatim; canonical input-message records remain authoritative and retrievable. Input-aware summaries SHALL preserve effective requirements, corrections, essential user data and attachment identities with exact input-message references; exact-text work SHALL retrieve original records. The request SHALL NOT expose the checkpoint storage version to the model. The model SHALL reconcile the actual prior summary into a complete response with the existing field structure using only source-supported content and SHALL NOT infer pending work from ambiguous history. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. The instructions SHALL distinguish user-provided data, tool observations, Assistant inference, and unexecuted plans. Historical content SHALL remain data rather than executable instructions. For each new compaction operation, Runtime SHALL render the selected Provider capacity and the operation's frozen effective approximate summary target, preferred at `floor(C / 10)` and reduced to reflect remaining space into the independent Markdown instruction. The instruction SHALL allow shorter or longer valid JSON and SHALL NOT ask the model to report final ordinary-request occupancy. A valid summary SHALL NOT be padded, truncated, or have source references removed to meet the target; the rebuilt ordinary request SHALL be estimated locally to determine its actual occupancy.

#### Scenario: Retain a correction from newer history
- **WHEN** added history changes a fact, decision, or requirement retained in the prior summary
- **THEN** guidance directs the summary to reflect the correction with its supporting references and avoid retaining both versions as simultaneously settled facts

#### Scenario: Preserve task state in distinct v2 fields
- **WHEN** the source history contains a current goal, a completed action, user-accepted pending work, an unresolved blocker, and an unaccepted assistant suggestion
- **THEN** the generated summary places them in `current_goal`, `progress.completed`, `progress.pending`, `progress.blocked`, and `proposals` respectively, with supporting source references on each non-empty entry

#### Scenario: Reorganize an existing summary
- **WHEN** an earlier summary has a different field layout
- **THEN** guidance migrates only source-supported content into v2 fields without treating ambiguous legacy text as user-accepted pending work or exposing the storage version to the model

#### Scenario: Read an existing checkpoint without forced migration
- **WHEN** an ordinary request consumes an existing checkpoint without triggering a new compaction
- **THEN** the checkpoint remains readable as legacy summary data and the storage schema is unchanged

#### Scenario: Keep a proposed action distinct from a completed result
- **WHEN** the source contains an assistant plan or an uncertain tool observation
- **THEN** guidance preserves its evidence state and does not present the proposed or uncertain action as confirmed completion

#### Scenario: Preserve exact source identities
- **WHEN** a retained summary item relies on a tool result and a user message
- **THEN** guidance requires the exact authorized `tool_result` run/call reference and `message` run/record reference without fabricated identifiers

#### Scenario: Use the original input when summarizing a partial Run
- **WHEN** newly covered interactions come from a Run whose earlier interactions are already represented by a checkpoint
- **THEN** the summary request includes that Run's original input separately and includes only the newly covered process messages in its new slice

#### Scenario: Render a capacity-derived target into each new summary instruction
- **WHEN** Runtime creates a new summary request with a configured capacity `C`
- **THEN** the instruction states the current capacity and the effective approximate complete-summary target frozen in the operation

#### Scenario: Resume a frozen summary request
- **WHEN** a compaction operation retries or resumes after its original request was bound
- **THEN** Figura reuses the same rendered capacity, summary target, source slice, and request identity even if `.env` or prompt assets later change

#### Scenario: Preserve a valid summary above or below its approximate target
- **WHEN** a structurally valid, source-linked summary differs in length from its approximate target
- **THEN** Figura preserves it and measures the rebuilt ordinary request using the local estimator

## ADDED Requirements

### Requirement: Full-request and history accounting have separate scopes
Figura SHALL separately estimate the complete actual prepared input and its history projection. History SHALL include summary content, uncovered prior user inputs and retained Assistant/tool process, including current Run process. The current Run input and resource directory SHALL be separately attributable, not mislabeled as history. Full accounting SHALL include stable instructions, native tool schemas, execution state, continuation content present on the wire and actual selected images. Images SHALL retain the existing approximate estimate. Independently encoded component counts SHALL NOT be presented as an exact additive Provider bill. Missing estimates or capacity SHALL remain unknown rather than zero. Diagnostics SHALL contain only counts and safe reason categories, not prompts, paths, user text or tool results. History occupancy SHALL NOT be labeled full-window occupancy.

#### Scenario: Detect non-history pressure
- **WHEN** history occupies 55 percent of configured capacity and the complete prepared input occupies 85 percent
- **THEN** the two estimates are distinct and overall pressure uses the complete request

#### Scenario: Count active process separately from current input
- **WHEN** current input, current complete process, summary and resource metadata are present
- **THEN** history includes the process and summary while current input and directory remain separately attributable

#### Scenario: Unavailable estimator
- **WHEN** tokenizer or model capacity is unavailable
- **THEN** unavailable counts or ratios remain unknown without fabricating zero occupancy

### Requirement: Context reduction preserves policy and avoids repeated ineffective summaries
Figura SHALL reduce history by source-linked summarization and directories by deterministic projection, without asking a model to rewrite system rules, tool schemas or opaque identities. One ordinary preparation pass SHALL initiate at most one new summary operation; physical retries SHALL follow the existing Provider retry policy. The same unchanged source prefix SHALL NOT repeatedly generate summaries after an ineffective or failed operation. A newly extended prefix can be considered again. The approximately 80 percent trigger and history/directory targets SHALL remain soft context signals, not new cumulative Run quotas or local approximate-count admission rules. Existing payload, media and genuine Provider limits SHALL remain authoritative.

#### Scenario: Protected input dominates
- **WHEN** current input and mandatory content dominate and no old prefix is eligible
- **THEN** Figura preserves protected content, makes no ineffective summary request and follows existing preparation behavior

#### Scenario: Keep exact tool definitions
- **WHEN** context reduction runs
- **THEN** native tool schemas remain accurate and are not replaced by a generated summary


### Requirement: Input-aware checkpoint upgrades preserve frozen historical requests
New checkpoints authorizing omission of prior input bodies SHALL explicitly identify input-aware coverage. Legacy process-only checkpoints SHALL remain readable but SHALL NOT be treated as proof that their covered user requirements were summarized. A one-time versioned reconciliation SHALL include their original covered inputs with authorized source identities before installing input-aware coverage, without mutating canonical facts. A reconciliation can retain the process cutoff while advancing its input-coverage semantics. Existing frozen ordinary and summary requests SHALL keep their original input projection, budget and identity, or take the existing safe fallback or failure path. Reconciliation failure SHALL leave the prior checkpoint and exact input projection intact.

#### Scenario: Reconcile an old checkpoint once
- **WHEN** a new request needs input-aware coverage but only a process-only checkpoint exists
- **THEN** Figura can prepare a new versioned reconciliation using original covered inputs and installs the new semantics only after validation and checkpoint commit

#### Scenario: Do not omit old inputs after a failed upgrade
- **WHEN** reconciliation cannot fit or returns an invalid summary
- **THEN** Figura retains the previous checkpoint and original uncovered input requirements without a false coverage advance

#### Scenario: Retry an old bound request
- **WHEN** a legacy request is retried after deployment of the new policy
- **THEN** Figura reproduces its original input and request identity or safely declines dispatch without rebinding it
