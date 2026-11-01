## MODIFIED Requirements

### Requirement: Compaction summarizes eligible complete history and retains a recent tail
Figura SHALL compact eligible committed process messages across prior Runs and the active Run by replacing a chronological prefix with a generated summary while retaining a recent raw process suffix and the active Run's exact current input. Every prior Run's complete persisted user input SHALL be projected separately in chronological order, regardless of summary coverage, and SHALL NOT be removed when its process messages enter a summary. The active Run's input SHALL remain its native user message and SHALL NOT be duplicated in the historical-input section. The raw suffix SHALL contain a source locator for each corresponding Run input rather than duplicating input text. The latest completed prior Run SHALL remain eligible for partial compaction. The active Run SHALL be eligible for compaction only through its last committed record/tool prefix at the time the compaction operation is bound. Compaction SHALL operate at complete interaction boundaries and SHALL NOT split an Assistant tool-call batch from any committed result. In-flight Provider work, uncommitted records, and incomplete tool-call batches SHALL remain raw and outside summary coverage. A failed or interrupted prior Run and later process history that cannot be crossed without newly summarizing that Run SHALL remain raw. If a Run becomes failed or interrupted after a committed prefix was already covered, Figura SHALL preserve that existing summary coverage and keep the terminal outcome and uncovered suffix raw. The raw-process budget and summary target SHALL be derived from the selected Provider's configured context capacity as specified by the compaction history budget requirement. Existing summary coverage SHALL be extended only with newly covered complete process interactions. Compaction SHALL NOT mutate, delete, or replace canonical Run facts.

The latest fully committed visual tool interaction awaiting ordinary model observation SHALL remain in the raw suffix with its assistant call batch, all results and attachment descriptions. Protected abnormal history or a spent raw budget SHALL NOT allow that interaction to enter the summary; the target is soft. The active Run's earlier complete interactions remain eligible. Summary sources SHALL include canonical business observations and attachment references/provenance without image bytes, generated hints or request-only images_loaded markers. A summary request SHALL NOT consume visual feedback. The next ordinary request and its retries SHALL attach the selected saved images only inside their retained owning tool results.

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
- **WHEN** the complete historical-input section or active input causes the prepared request to exceed the selected Provider's usable capacity
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
