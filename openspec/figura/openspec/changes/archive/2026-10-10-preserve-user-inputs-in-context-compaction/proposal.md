## Why

Context compaction currently treats a Run's user input as part of its first interaction unit. Once that unit is summarized, the original user input disappears from the ordinary Provider request and later incremental summaries may only see a paraphrase. Users want their complete historical inputs to remain available verbatim so task goals, constraints, corrections, and attachment references do not depend on the summary model retaining them.

## What Changes

- Project every prior Run's complete persisted user input into one ordered, source-linked prompt section, independently of the compaction coverage cursor.
- Keep the active Run's input in its native user message and avoid duplicating it in the historical-input section.
- Represent historical user messages in retained raw interaction context with a compact source pointer to the dedicated input section; keep assistant messages, tool-call batches, and all committed results at their existing complete interaction boundaries.
- Include the source Run's original input as context when summarizing newly covered interactions, while keeping the generated summary concise and source-linked.
- Count the complete historical-input section and its raw-context pointers in the actual prepared-request token estimate. Keep the existing raw-history and summary budgets as separate soft budgets derived from the selected Provider capacity.
- Insert the dynamically computed summary target into the compaction Markdown instruction for each new operation; keep the target approximate and preserve the operation's existing frozen retry and recovery binding.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `session-context-compaction`: historical user inputs remain verbatim in ordinary requests independently of compaction coverage; raw history references the dedicated input section, and summary requests receive the original input for each source Run.

## Impact

- Agent request projection and context-compaction selection/request construction under `src/figura/agent/`.
- The compaction prompt asset under `src/figura/agent/prompting/assets/`.
- Existing session-context-compaction OpenSpec behavior and focused request/compaction tests.
- No new database storage is required because the authoritative input text, attachment IDs, and input-record identity already exist in each persisted Run.
- Ordinary request size may grow with the number and length of historical user inputs; the existing local estimator measures the full assembled request, including this section.
