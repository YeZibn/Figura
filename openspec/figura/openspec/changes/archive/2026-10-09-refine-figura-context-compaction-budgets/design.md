## Context

See `proposal.md` for the motivation and `specs/session-context-compaction/spec.md` for the behavior contract.

The current executor estimates the prepared ordinary request against the selected Provider capacity and invokes compaction at approximately 80%. Selection in `context_compaction.py` is Run-based: it keeps the newest prior Run raw and summarizes only earlier completed Runs. Ordinary request projection filters history by `covered_run_ordinal`, even though the persisted checkpoint and compaction operation also carry record and tool sequence cutoffs. `build_summary_request` serializes whole selected Runs. The independent `compaction.md` asset currently contains a 4,000-token soft target; the 2026-10-09 token-target experiment showed that this cue increased mean valid-summary size by 16.8% and reduced the measured first-request saving versus the no-target baseline.

## Goals / Non-Goals

**Goals:**

- Derive the historical raw-tail and rolling-summary budgets from the selected Provider/model's configured context capacity.
- Let the latest completed prior Run be summarized up to a safe interaction boundary while retaining a recent raw suffix.
- Make partial Run coverage consistent across summary input, ordinary history projection, resource projection, checkpoint validation, and recovery.
- Preserve exact source references and canonical Run facts, and measure the actual rebuilt request rather than claiming an occupancy from the summary target.

**Non-Goals:**

- Changing the existing approximate 80% automatic-compaction trigger.
- Limiting ordinary Run completion output or truncating generated summaries to meet an approximate target.
- Changing the v2 summary fields, history tools, resource catalog ownership, or canonical Run storage.
- Promising that the complete prepared request is at most 20% of capacity; system instructions, tools, resources, the active Run, and protected abnormal tails remain additional content.
- Adding summary chunking or a second compaction loop unless the actual prepared summary request cannot fit the selected Provider context.

## Decisions

### Derive budgets once from the selected Provider profile

Use the context capacity attached to the actual selected Provider/model request, `C`. Compute `raw_history_budget_tokens = floor(C / 10)` and `summary_budget_tokens = floor(C / 10)`. At the current local DeepSeek setting (`C = 200,000`), both are approximately 20,000; at `C = 1,000,000`, both are approximately 100,000. These are allocations for history projection, not a promise about total prepared-request occupancy and not a required summary length.

If capacity or the prepared-request estimator is unavailable, keep the existing no-automatic-compaction behavior. Do not fall back to a hard-coded capacity or budget.

### Select a suffix by complete interaction units

Build an ordered history-unit projection from persisted records and tool facts. An assistant response containing a tool-call batch and all of that batch's committed results is one indivisible unit. Other closed assistant/user material remains attached to the closest complete interaction so that the summary or raw suffix never loses the request that gives an observation meaning.

Starting at the newest prior-history unit, accumulate whole units backward until adding the next unit would exceed the raw-history budget. The remaining older prefix, including older interactions from the latest completed Run, becomes the source slice for the rolling summary. If one newest unit alone exceeds the budget, preserve it intact and accept the overshoot. A failed or interrupted prior Run closes the eligible chronological prefix; that Run and all later history stay raw so coverage never skips abnormal facts. The current active Run and its required committed prefix remain outside historical compaction.

This replaces “keep the newest entire Run” with “keep the newest complete interactions up to an approximate token budget.” A short Run can naturally remain entirely raw if it fits; a longer Run can contribute both summarized earlier interactions and raw recent interactions.

### Use the existing sequence coordinates for partial coverage

Represent the summary cutoff as the existing tuple `(covered_run_id, covered_run_ordinal, covered_record_sequence, covered_tool_sequence)`, chosen only after a complete interaction boundary. The sequence pair lets a checkpoint cover a prefix of a Run while the same Run's later messages remain in the raw suffix; no new table or checkpoint column is required.

Update the projection and validation paths to compare each projected message or tool result against that exact cutoff when its Run ordinal equals `covered_run_ordinal`. Messages and facts from earlier ordinals remain covered; later ordinals remain raw. The summary builder receives only the newly covered slice after the prior checkpoint, plus the prior summary and its references. Resource-locator projection uses the same cutoff so resources needed by retained raw history or summary references remain discoverable. History search and precise reads continue to operate on canonical facts.

The selector must prove that the sequence pair ends after all committed results in a tool-call batch before it can advance coverage. If the current record/fact relationships cannot express that boundary unambiguously, stop and extend the durable coverage contract rather than storing a partial checkpoint with an ambiguous cutoff.

### Freeze the budget and cutoff for recovery

Persist the calculated capacity, both budget values, selected cutoff, prior checkpoint revision, and summary request identity in the durable compaction operation binding. A retry of an in-progress operation reuses that frozen plan even if the process restarts or environment values change. A later, new compaction operation uses the then-selected Provider capacity and calculates fresh budgets. Keep the existing optimistic checkpoint replacement: install a newly validated summary and its expanded coverage atomically against the expected prior revision.

This keeps request identity deterministic and prevents a retry from silently changing its source slice or target because `.env` changed mid-operation.

### Treat summary size as a soft budget and keep the number out of the prompt

Remove the fixed 4,000-token sentence from the static asset. Calculate and persist `summary_budget_tokens` in the coordinator as a soft allocation, but keep the literal number out of model-facing compaction instructions. The prompt asks for concise, source-supported coverage and does not request that the model fill a length budget. Do not use the summary budget as `max_completion_tokens`, reject a valid summary solely for exceeding it, remove source references, or truncate JSON. Use the same local prepared-payload estimator to measure the rebuilt ordinary request after compaction.

The paired dynamic-cue pilot at `C = 200,000` validated two summaries per prompt variant; the third history failed with a Provider connection error under both variants. In the two valid pairs, a `20,000`-token soft-budget cue increased mean summary JSON size from 2,960 to 3,188 estimated tokens (about 7.7%) while changing first-request reduction from 38.14% to 38.02%. This is a small directional sample, but it offers no measurable benefit for exposing the number and is consistent with the earlier fixed 4,000-token target experiment. Keep the budget in request coordination and omit its numeric value from the production prompt.

### Preflight the summary request separately

Prepare and estimate the tool-free summary request before dispatch. It uses the selected Provider/model, prior summary, and only the authorized history slice being covered. If that prepared summary request cannot fit the configured context, preserve the prior checkpoint and use the existing safe fallback/failure behavior; never truncate source history to force dispatch. The current 80% trigger and 10% summary allocation should leave practical headroom for the normal case, so bounded multi-request summary batching is deferred unless tests demonstrate that it is needed.

## Risks / Trade-offs

- [Numeric token cues can make summaries longer] → Both the earlier fixed-target experiment and the dynamic-cue pilot showed larger summaries with a numeric cue. Keep the dynamic allocation in the coordinator, but omit its literal value from the production prompt.
- [A complete tool interaction can exceed 10%] → Treat the budgets as approximate and preserve the interaction rather than splitting it or losing its source/result relationship.
- [Current Run or protected abnormal history dominates the request] → Keep it intact and use the post-compaction estimate as the actual result; do not claim that the 20% history allocation is the total request occupancy.
- [A partial checkpoint interpreted by old code as whole-Run coverage could hide the raw suffix] → Persist partial cutoffs only with the updated reader/projection code. Treat rollback to a binary that filters only by Run ordinal as unsafe after partial coverage has been written; deployment rollback must first restore a compatible checkpoint/database snapshot or use a forward-compatible recovery path.
- [Summary source payload is itself too large] → Preflight its actual prepared request. Preserve the old checkpoint on failure; add durable batched summarization only if a concrete test proves it necessary.

## Migration Plan

No database schema migration is expected: `SessionContextCheckpoint` and `ContextCompactionOperation` already persist Run ordinal plus record/tool sequence cutoffs. Existing whole-Run checkpoints remain readable under the new projection. Deploy the code that understands partial coverage before any partial checkpoint can be written. If rollback is required after that point, do not run an ordinal-only reader against the same checkpoint state; restore a compatible database snapshot or complete a forward recovery first.

## Open Questions

None. The 80% trigger, two dynamic 10% history budgets, protected current Run, soft summary target, and the distinction between history allocation and total request occupancy are settled by this design.
