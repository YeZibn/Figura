## 1. Dynamic budgets and complete history units

- [x] 1.1 Add a pure budget calculation from the selected Provider context capacity: approximately 10% for raw recent history and 10% for the rolling summary; cover missing/invalid capacity and multiple configured capacities.
- [x] 1.2 Project prior Run facts into chronological complete interaction units, keeping each assistant tool-call batch and all committed results indivisible.
- [x] 1.3 Replace newest-whole-Run protection with token-estimated suffix selection that can include earlier interactions from the latest completed Run in the summary; preserve active and incomplete abnormal Run tails.
- [x] 1.4 Add selector tests for exact-budget boundaries, an interaction larger than the budget, one prior Run, a partially retained latest Run, and an incomplete abnormal tail.

## 2. Partial coverage and durable recovery

- [x] 2.1 Validate that the existing Run/record/tool sequence coordinates represent a cutoff only at a fully committed interaction boundary; retain the existing checkpoint storage shape for whole-Run checkpoints.
- [x] 2.2 Update checkpoint and compaction-operation validation so summary source references and coverage sequences may end within the covered Run without admitting records or tool results after the cutoff.
- [x] 2.3 Update summary request construction to combine the previous summary with only the newly covered history slice, including a partial slice of the latest completed Run.
- [x] 2.4 Update ordinary history, Run outcome, and resource-locator projections to retain same-Run content after the cutoff while omitting only content represented by the summary.
- [x] 2.5 Freeze context capacity, raw-tail and summary budgets, coverage coordinates, and request identity in the durable compaction operation; verify retry/recovery remains identical if env configuration changes mid-operation.
- [x] 2.6 Add persistence and recovery tests for partial coverage, compare-and-swap replacement, source-reference validation, restart, and preservation of the previous checkpoint after failure.

## 3. Summary request and execution integration

- [x] 3.1 Remove the fixed 4,000-token wording from `compaction.md` and implement concise summary guidance that treats the dynamically computed summary allocation as soft, does not ask the model to fill it, and never truncates valid source-linked JSON.
- [x] 3.2 Bind any dynamic summary-budget instruction into the prompt digest and retry identity; run the planned comparison against a concise prompt without a numeric cue and use the observed summary size and request savings to finalize the model-facing wording.
- [x] 3.3 Preflight the actual prepared summary request against the selected Provider capacity; preserve the previous checkpoint and use existing safe fallback behavior if the summary request cannot be prepared safely.
- [x] 3.4 Rebuild and locally estimate the ordinary request after compaction, keeping the existing 80% trigger and distinguishing historical budget totals from full-request occupancy.
- [x] 3.5 Add Agent integration tests for automatic selection, latest-Run partial coverage, dynamic Provider budgets, oversized valid summaries, invalid summaries, and failed Provider attempts.

## 4. Evaluation, documentation, and validation

- [x] 4.1 Extend the fixed-history compaction evaluation to compare full-history and budgeted projections at multiple configured capacities, including first-request local token estimates, summary size, cumulative Provider usage, and source-fact recovery.
- [x] 4.2 Record the experiment conditions and results without presenting synthetic histories as real user sessions or treating local estimates as billed token counts.
- [x] 4.3 Update the main `session-context-compaction` specification and Figura Agent/Runtime implementation documentation to match the shipped partial-Run coverage and budget semantics.
- [x] 4.4 Run targeted context-compaction, checkpoint, history-retrieval, and token-estimation tests; run the full Python suite and report unrelated pre-existing failures separately.
- [x] 4.5 Run `openspec validate refine-figura-context-compaction-budgets --type change --strict --store figura` and `git diff --check`.
