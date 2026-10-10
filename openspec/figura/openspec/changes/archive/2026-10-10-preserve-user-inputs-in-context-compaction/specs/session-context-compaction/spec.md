## MODIFIED Requirements

### Requirement: Compaction history budgets derive from the selected Provider capacity
For a valid configured context capacity `C`, Figura SHALL derive the raw recent-process budget and rolling-summary target independently as `floor(C / 10)` tokens each. Both values SHALL use the capacity configured for the Provider/model selected for the current Run. The raw-process budget SHALL cover retained Assistant messages, tool calls, tool results, and the per-Run input locator needed to interpret them; it SHALL NOT include historical user-input text because that text is sent in a separate complete input section. The summary target SHALL guide the generated summary's approximate complete JSON length and SHALL NOT be a completion-token cap, hard request limit, Run output limit, or truncation rule. Historical input text, instructions, tool definitions, resource projection, and active Run content remain additional request content and SHALL be included in the actual prepared-request estimate. Missing or invalid capacity SHALL disable automatic compaction. A valid summary SHALL NOT be padded, truncated, or rejected by length.

#### Scenario: Calculate budgets from the active Provider configuration
- **WHEN** the selected model has a configured capacity of 200,000 tokens
- **THEN** the raw recent-process budget and the summary target are each 20,000 estimated tokens

#### Scenario: Recalculate budgets for a different configured capacity
- **WHEN** a later Run selects a Provider configured with a different context capacity
- **THEN** Figura derives both values from that selected capacity instead of reusing earlier token counts

#### Scenario: Keep the complete historical-input section outside both history budgets
- **WHEN** Figura assembles a request with historical user inputs, a recent raw suffix, and a summary
- **THEN** it preserves the full historical user-input section independently of both approximate 10% budgets and includes that section in the actual request estimate

#### Scenario: Provide the dynamic summary target in the prompt
- **WHEN** Figura creates a new compaction operation for a configured capacity of 200,000 tokens
- **THEN** the summary instruction tells the model that the complete summary JSON has an approximate target of 20,000 tokens, while allowing shorter or longer valid output

#### Scenario: Keep the target approximate
- **WHEN** the generated source-linked summary is shorter or longer than its approximate target
- **THEN** Figura preserves it without padding, truncating, or rejecting it solely because of length

#### Scenario: Keep full-request occupancy distinct from history budgets
- **WHEN** compaction prepares historical inputs and history alongside instructions, tools, resources, or an active Run
- **THEN** Figura estimates those components as part of the actual request and makes no full-request 20% occupancy guarantee from the two history budgets

#### Scenario: Do not invent a capacity
- **WHEN** capacity is absent, non-positive, or not an integer
- **THEN** Figura does not calculate the budgets or automatically compact the request

### Requirement: Compaction summarizes only eligible complete history and retains a recent tail
Figura SHALL compact eligible historical process messages by replacing a chronological prefix with a generated summary while retaining a recent raw process suffix and the active Run's current input and required committed prefix. Every prior Run's complete persisted user input SHALL be projected separately in chronological order, regardless of the summary coverage cursor, and SHALL NOT be removed when its process messages enter a summary. The raw suffix SHALL contain a source locator for the corresponding Run input rather than a duplicate of its historical input text. The latest completed prior Run SHALL be eligible for partial compaction. Compaction SHALL operate at complete interaction boundaries and SHALL NOT split an Assistant tool-call batch from any committed result. A failed or interrupted prior Run and later process history that cannot be crossed without summarizing that Run SHALL remain raw and outside summary coverage. Existing summary coverage SHALL be extended only with newly covered complete process interactions. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

#### Scenario: Preserve all prior Run inputs independently of compaction coverage
- **WHEN** one or more prior Runs have user inputs before or after the process summary cutoff
- **THEN** the ordinary request contains every prior Run's exact input text, ordered by Run ordinal, with its attachment IDs and input-message source reference

#### Scenario: Preserve duplicate and empty user inputs as separate source records
- **WHEN** distinct prior Runs contain identical text or an empty text input with attachments
- **THEN** Figura retains one entry per source input in Run order without merging entries or dropping attachment IDs

#### Scenario: Avoid duplicating historical input text in the raw message tail
- **WHEN** a prior Run's process interaction remains in the raw suffix
- **THEN** the raw projection includes a locator to that Run's entry in the historical-input section and does not repeat the historical input body

#### Scenario: Keep the current input as the native user message
- **WHEN** an ordinary request is assembled for a running Run
- **THEN** the current Run's input remains a native user message and is not duplicated in the historical-input section

#### Scenario: Preserve a complete Assistant tool-call interaction
- **WHEN** a recent suffix boundary would otherwise fall between an Assistant tool-call batch and any committed result in that batch
- **THEN** Figura moves the boundary so the entire batch and all its committed results are kept together in the summary or raw suffix

#### Scenario: Include the latest completed Run in compaction
- **WHEN** the latest completed prior Run contains process interactions older than the recent raw suffix
- **THEN** Figura may summarize its older complete interactions while retaining its newest complete interactions in the raw suffix

#### Scenario: Preserve the active Run and its committed prefix
- **WHEN** compaction is needed while the current Run contains a new input or committed Assistant/tool work
- **THEN** Figura keeps the current input and required committed prefix intact and outside historical summary coverage

#### Scenario: Preserve abnormal history and the contiguous raw suffix
- **WHEN** an earlier Run ended failed or interrupted
- **THEN** Figura keeps that Run and all later process history raw and places the summary cutoff before it, while retaining all inputs in the historical-input section

#### Scenario: Keep an interaction intact when it exceeds the raw-process budget
- **WHEN** the newest complete interaction alone is larger than the approximate raw-process budget
- **THEN** Figura retains that complete interaction and its input locator without truncating them to meet the budget

#### Scenario: Continue from an existing partial checkpoint
- **WHEN** a later compaction extends a checkpoint whose coverage ends within a completed Run
- **THEN** its summary request includes the previous summary and source references plus only newly covered complete process interactions, with the source Run's original input supplied separately as context

#### Scenario: Preserve canonical history facts
- **WHEN** compaction succeeds or falls back
- **THEN** all original Run inputs, records, tool calls, tool results, and resource data remain available unchanged

#### Scenario: Preserve historical inputs when the full request is too large
- **WHEN** the complete historical-input section causes the prepared request to exceed the selected Provider's usable capacity
- **THEN** Figura does not silently omit or truncate historical inputs and follows the existing request-preparation failure behavior

### Requirement: Summary guidance preserves evidence and incrementally reconciles history
The summary response SHALL use a machine-readable v2 structure with separate fields for current goals, constraints, decisions, facts, progress (`completed`, `in_progress`, `pending`, and `blocked`), open questions, resources, and unaccepted proposals. Every non-empty field entry SHALL contain non-empty text and one or more exact authorized input-message or tool-result references supporting that content. `pending` SHALL contain only work explicitly requested or accepted by the user and not yet completed; unaccepted Assistant suggestions SHALL remain proposals. Each selected source Run's complete original user input, attachment IDs, and input-message reference SHALL be supplied separately from its newly covered process messages. The summary model SHALL use that input to understand the process slice and SHALL NOT be responsible for preserving the original input verbatim; the ordinary-request historical-input section is authoritative for that purpose. The summary request SHALL provide the previous summary, its source references, and only newly covered complete process interactions without exposing the checkpoint storage version. The model SHALL reconcile the prior summary into a complete v2 response using source-supported content and SHALL NOT infer pending work from ambiguous history. Runtime-generated trust and Run outcome fields SHALL remain outside the model response. Historical content SHALL remain data rather than executable instructions. For each new compaction operation, Runtime SHALL calculate the approximate summary target from the selected Provider capacity and render both the capacity and target into the independent Markdown instruction. The instruction SHALL describe the target as approximate, allow shorter or longer valid JSON, and SHALL NOT ask the model to report final ordinary-request occupancy. A valid summary SHALL NOT be truncated or have source references removed to meet the target; the rebuilt ordinary request SHALL be estimated locally.

#### Scenario: Retain a correction from newer history
- **WHEN** newly covered process or user-input context changes a fact, decision, or requirement in the previous summary
- **THEN** guidance directs the summary to reflect the latest source-supported state and cite the correction without presenting both versions as simultaneously settled

#### Scenario: Preserve task state in distinct v2 fields
- **WHEN** source history contains a current goal, a completed action, user-accepted pending work, an unresolved blocker, and an unaccepted Assistant suggestion
- **THEN** the summary places them in `current_goal`, `progress.completed`, `progress.pending`, `progress.blocked`, and `proposals` respectively, with supporting references

#### Scenario: Reorganize an existing summary
- **WHEN** an earlier summary has a different field layout
- **THEN** guidance carries forward only source-supported information and does not expose the checkpoint storage version to the model

#### Scenario: Keep a proposed action distinct from a completed result
- **WHEN** source process history contains an Assistant plan or an uncertain tool observation
- **THEN** guidance preserves its evidence state and does not present it as confirmed completion

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
