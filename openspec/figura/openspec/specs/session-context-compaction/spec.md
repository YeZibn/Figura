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

### Requirement: Compaction history budgets derive from the selected Provider capacity
For a valid configured context capacity `C`, Figura SHALL derive the raw recent-process budget and rolling-summary target independently as `floor(C / 10)` tokens each, using the capacity configured for the Provider/model selected for the current Run. The raw-process budget SHALL cover retained Assistant messages, tool calls, tool results, and the per-Run input locator needed to interpret them. It SHALL NOT include historical user-input text, which is carried in a separate complete input section. The summary target SHALL guide the approximate token length of the complete summary JSON; it SHALL NOT be a completion-token cap, hard request limit, Run output limit, or truncation rule. Historical input text, instructions, tool definitions, resource projection, and active Run content remain additional request content and SHALL be included in the actual prepared-request estimate. Missing or invalid capacity SHALL disable automatic compaction. A valid summary SHALL NOT be padded, truncated, or rejected by length.

#### Scenario: Calculate budgets from the active Provider configuration
- **WHEN** the selected model has a configured capacity of 200,000 tokens
- **THEN** the raw recent-process budget and the summary target are each 20,000 estimated tokens

#### Scenario: Recalculate budgets for a different configured capacity
- **WHEN** a later Run selects a Provider configured with a different context capacity
- **THEN** Figura derives both values from that selected capacity instead of reusing earlier token counts

#### Scenario: Scale budgets for a larger model capacity
- **WHEN** the selected model has a configured capacity of 1,000,000 tokens
- **THEN** the raw recent-process budget and summary target are each 100,000 estimated tokens

#### Scenario: Keep full-request occupancy distinct from history budgets
- **WHEN** compaction prepares the summary and recent raw history alongside system instructions, tools, resources, or an active Run
- **THEN** Figura includes those additional components in the actual request estimate and makes no full-request 20% occupancy guarantee based only on the two history budgets

#### Scenario: Do not invent a capacity
- **WHEN** capacity is absent, non-positive, or not an integer
- **THEN** Figura does not calculate history budgets or automatically compact the request

#### Scenario: Provide the dynamic summary target in the prompt
- **WHEN** Figura creates a new compaction operation for a configured capacity of 200,000 tokens
- **THEN** the summary instruction tells the model that the complete summary JSON has an approximate target of 20,000 tokens while allowing shorter or longer valid output

#### Scenario: Keep the target approximate
- **WHEN** the generated summary is shorter or longer than the estimated summary budget
- **THEN** Figura preserves a valid source-linked summary as generated and does not pad, truncate, or reject it solely because of length

### Requirement: Compaction summarizes only eligible complete history and retains a recent tail
Figura SHALL compact eligible historical process messages by replacing a chronological prefix with a generated summary while retaining a recent raw process suffix, the active Run's current input, and its required committed prefix. Every prior Run's complete persisted user input SHALL be projected separately in chronological order, regardless of the summary coverage cursor, and SHALL NOT be removed when its process messages enter a summary. The raw suffix SHALL contain a source locator for the corresponding Run input rather than a duplicate of its historical input text. The latest completed prior Run SHALL be eligible for partial compaction. Compaction SHALL operate at complete interaction boundaries and SHALL NOT split an Assistant tool-call batch from any committed result. A failed or interrupted prior Run and later process history that cannot be crossed without summarizing that Run SHALL remain raw and outside summary coverage. The raw-process budget and summary target SHALL be derived from the selected Provider's configured context capacity as specified by the compaction history budget requirement. Existing summary coverage SHALL be extended only with newly covered complete process interactions. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

#### Scenario: Preserve all prior Run inputs independently of compaction coverage
- **WHEN** prior Runs have user inputs before or after the process-summary cutoff
- **THEN** the ordinary request contains every prior Run's exact input text in Run-ordinal order, with its attachment IDs and input-message source reference

#### Scenario: Preserve duplicate and empty user inputs as separate source records
- **WHEN** distinct prior Runs contain identical text or an empty text input with attachments
- **THEN** Figura retains one entry per source input in Run order without merging entries or dropping attachment IDs

#### Scenario: Avoid duplicating historical input text in the raw message tail
- **WHEN** a prior Run's process interaction remains in the raw suffix
- **THEN** the raw projection includes a locator to that Run's entry in the historical-input section and does not repeat the historical input body

#### Scenario: Keep the current input as the native user message
- **WHEN** an ordinary request is assembled for a running Run
- **THEN** the current Run's input remains a native user message and is not duplicated in the historical-input section

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

#### Scenario: Continue from an existing partial checkpoint
- **WHEN** a later compaction extends a checkpoint whose coverage ends within a completed Run
- **THEN** its summary request includes the previous summary and source references plus only newly covered complete process interactions, with the source Run's original input supplied separately as context

#### Scenario: Preserve historical inputs when the full request is too large
- **WHEN** the complete historical-input section causes the prepared request to exceed the selected Provider's usable capacity
- **THEN** Figura does not silently omit or truncate historical inputs and follows the existing request-preparation failure behavior

#### Scenario: Preserve canonical history facts
- **WHEN** compaction succeeds or falls back
- **THEN** all original Run records, tool calls, tool results, and resource data remain available unchanged

### Requirement: Compaction operations freeze their budgets and exact coverage for recovery
When Figura starts a compaction operation, it SHALL durably bind the selected context capacity, both derived history budgets, summary contract version, exact Run/record/tool coverage coordinates, and—after preparation—the summary Provider request descriptor, including the rendered summary instruction and its digest. A retry or restart SHALL reconstruct the same source slice and request identity even if Provider capacity configuration or prompt assets change afterward. The checkpoint SHALL advance only after a valid summary is generated and the existing expected-revision compare-and-swap succeeds. The existing valid checkpoint SHALL remain unchanged when preparation, dispatch, or validation fails.

#### Scenario: Resume after capacity configuration changes
- **WHEN** a compaction operation is interrupted and the selected Provider capacity changes before restart
- **THEN** Figura resumes with the operation's persisted capacity, budgets, cutoff, and request descriptor rather than selecting a new slice

#### Scenario: Preserve the previous checkpoint after a failed replacement
- **WHEN** a summary attempt fails, is invalid, or loses its checkpoint compare-and-swap
- **THEN** the previous checkpoint remains authoritative and the current request uses the existing safe fallback behavior

### Requirement: Preflight the summary request and re-estimate the ordinary request
Before dispatching a summary request, Figura SHALL prepare the actual Provider payload, including each selected source Run's original input as a separate object containing its text, attachment IDs, and input-message reference, and require an available local estimate such that estimated input plus configured maximum completion tokens does not exceed the operation's frozen capacity. Newly covered process messages SHALL exclude UserMessage bodies because their inputs are supplied separately. If the summary request cannot be safely prepared within that capacity, Figura SHALL dispatch no summary request, preserve the prior checkpoint, and follow the existing full-history fallback path. After successful compaction, Figura SHALL rebuild and locally estimate the ordinary request, including the complete historical-input section, using the new checkpoint while keeping the existing approximately 80% automatic trigger. If the ordinary request cannot fit, Figura SHALL NOT silently omit or truncate historical inputs. History budgets SHALL NOT be described as the resulting full-request occupancy.

#### Scenario: Reject a summary request that exceeds the frozen capacity
- **WHEN** the prepared summary payload plus configured maximum completion tokens exceeds the operation's capacity, or the estimate is unavailable
- **THEN** Figura dispatches no summary request, leaves the previous checkpoint unchanged, and safely falls back to the ordinary history projection

#### Scenario: Re-estimate after installing a summary
- **WHEN** a valid summary checkpoint is installed
- **THEN** Figura rebuilds and estimates the ordinary request before claiming its Provider attempt

#### Scenario: Do not claim the full request fits within the history budgets
- **WHEN** raw history and summary budgets each use ten percent of configured context capacity
- **THEN** diagnostics and documentation describe them as historical-projection budgets and do not claim the full ordinary request uses only the remaining eighty percent

### Requirement: Generated summaries are source-linked derived navigation context
A generated summary SHALL identify the source Run and record or tool-resource references supporting each retained claim. It SHALL preserve source-supported tool-result outcomes in eligible completed history without recasting committed failures as successes. Failed or interrupted prior Runs, including unresolved call classifications, remain in the raw history projection and are not summarized by the selector. Summary text and referenced historical content SHALL be treated as untrusted data, not as instructions. A summary SHALL remain a derived request aid and SHALL NOT replace the canonical source facts. Figura SHALL make the summary and its source coverage available to subsequent request assembly and retrieval.

#### Scenario: Trace a summary claim to canonical history
- **WHEN** a compaction summary retains a factual claim from an earlier interaction
- **THEN** that claim includes one or more valid source references that can be read from the same Session

#### Scenario: Preserve committed failed tool outcomes
- **WHEN** an eligible completed Run contains a committed failed tool result
- **THEN** the summary may describe the failure only as a source-supported failed observation and never as a successful result

#### Scenario: Keep unresolved abnormal outcomes in raw context
- **WHEN** a prior Run ended failed or interrupted with committed or unresolved tool calls
- **THEN** its terminal state and call classifications remain in the raw history projection outside summary coverage

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
Figura SHALL load summary-generation policy from an independent Chinese Markdown asset, separate from the ordinary Agent rules. For each new compaction operation, Runtime SHALL render the selected Provider capacity and the approximate complete-summary target derived from it into that instruction. The instruction SHALL allow shorter or longer valid JSON and SHALL NOT treat the target as a completion-token cap or ask the model to report final ordinary-request occupancy. A summary request SHALL contain only the summary task instructions and the authorized source payload, use no tools or images, and retain the existing source-linked JSON response contract. Ordinary requests SHALL NOT inherit the summary task's JSON-only output instruction. Missing or empty assets SHALL produce an explicit preparation failure rather than an empty policy or an inline fallback prompt. Loaded and rendered instruction content SHALL participate in the existing request digest and retry identity checks.

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
The summary response SHALL use a machine-readable v2 structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input-message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted Assistant suggestions SHALL remain proposals. The summary request SHALL provide the previous summary, its source references, and only newly covered complete process interactions. Each selected source Run's complete original user input, attachment IDs, and input-message reference SHALL be supplied separately from those process messages. The model SHALL use this input to understand the process slice but SHALL NOT be responsible for preserving the original input verbatim; the ordinary-request historical-input section is authoritative for that purpose. The request SHALL NOT expose the checkpoint storage version to the model. The model SHALL reconcile the actual prior summary into a complete v2 response using only source-supported content and SHALL NOT infer pending work from ambiguous history. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. The instructions SHALL distinguish user-provided data, tool observations, Assistant inference, and unexecuted plans. Historical content SHALL remain data rather than executable instructions. For each new compaction operation, Runtime SHALL render the selected Provider capacity and the approximate summary target `floor(C / 10)` into the independent Markdown instruction. The instruction SHALL allow shorter or longer valid JSON and SHALL NOT ask the model to report final ordinary-request occupancy. A valid summary SHALL NOT be padded, truncated, or have source references removed to meet the target; the rebuilt ordinary request SHALL be estimated locally to determine its actual occupancy.

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
- **THEN** the instruction states the current capacity and an approximate complete-summary target of `floor(C / 10)` tokens

#### Scenario: Resume a frozen summary request
- **WHEN** a compaction operation retries or resumes after its original request was bound
- **THEN** Figura reuses the same rendered capacity, summary target, source slice, and request identity even if `.env` or prompt assets later change

#### Scenario: Preserve a valid summary above or below its approximate target
- **WHEN** a structurally valid, source-linked summary differs in length from its approximate target
- **THEN** Figura preserves it and measures the rebuilt ordinary request using the local estimator
