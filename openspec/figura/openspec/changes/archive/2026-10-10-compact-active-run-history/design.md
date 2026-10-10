## Context

See [proposal.md](proposal.md) for the motivation and [the delta spec](specs/session-context-compaction/spec.md) for the behavior contract. Today the ordinary-request estimator sees the active Run, but compaction selection receives only prior Run states. Runtime also rejects a checkpoint whose covered Run is still running, and request assembly applies the session checkpoint only to prior history before appending the active Run unchanged.

The persisted checkpoint and compaction-operation records already carry the covered Run ID/ordinal and record/tool coordinates, plus the target Run's committed base coordinates. The main constraints are therefore the validation and projection invariants: an active Run can only be summarized through a committed complete interaction boundary, while its current user input and any unresolved work remain available to the model.

## Goals / Non-Goals

**Goals:**

- Make the `floor(C / 10)` raw-tail selection span eligible completed history and the active Run's stable committed process prefix.
- Let an incremental summary checkpoint end inside the active Run and apply that checkpoint to later requests in the same Run.
- Preserve exact user inputs and all canonical execution facts; never summarize uncommitted or incomplete work.
- Keep compaction retries and recovery bound to the original active Run prefix and summary request identity.

**Non-Goals:**

- Changing the approximately 80% trigger, the two independent `floor(C / 10)` targets, the v2 summary shape, or Provider retry policy.
- Removing, paraphrasing, deduplicating, or charging exact user-input text against the raw-process budget.
- Compacting an in-flight Provider request or a partially committed tool-call batch.
- Adding a user-facing control, a second memory store, or a new tool/API.

## Decisions

### 1. Select from one chronological process stream through the active committed prefix

At a fresh model-request boundary, form the candidate process stream from newly eligible complete interactions after the existing session checkpoint: eligible prior Runs first, then the active Run's interactions no later than its `last_committed_record_sequence` and `last_committed_tool_sequence`. The active Run is a source only through this frozen prefix; later records cannot enter an already-created operation.

Run the existing newest-to-oldest raw-tail selection once over that combined chronological stream. `floor(C / 10)` is one budget shared across prior and active process, not a per-Run allowance. The chronological prefix before the retained suffix becomes the new summary coverage. If the newest complete interaction alone exceeds the target, keep it whole. If an incomplete batch or other unresolved active work cannot form a complete interaction, keep it raw outside coverage and account for its protected context when choosing the suffix.

This is preferable to merely adding active messages to the budget estimate: counting active messages without allowing them into the summary would not reclaim the context that caused the trigger. Delaying their compaction until Run completion has the same limitation for long Runs.

### 2. Keep user input authoritative and outside the process budget

The active Run's original input remains the ordinary request's native user message. Prior Run inputs remain in the ordered historical-input section. When a summary covers process from a Run, pass that Run's complete input, attachment IDs, and source reference separately in the summary payload; do not include the input body in the raw-process token budget or remove it from ordinary requests. A retained process segment uses a Run-input locator rather than copying the full input again.

The ordinary prepared-request estimate continues to include all user inputs, the current Run, instructions, tools, resources, and other Provider payload. The summary-request preflight also counts the selected source inputs and process slice against its frozen capacity. This preserves the existing exact-input rule while letting the current Run's process be compacted.

### 3. Treat committed action boundaries as the only active-Run source boundary

Compaction starts only before a new ordinary Provider attempt, after the previous external action has reached a durable checkpoint. Bind the active Run's base record/tool sequences into the compaction operation. The selector and summary builder must not read source facts beyond that base, even if new facts appear while reconstructing or retrying.

Only a complete interaction can be covered: an Assistant response and its complete tool-call batch with all committed results stay together. An unresolved Provider attempt, uncommitted record, partial tool batch, or incomplete outcome remains raw. The new checkpoint may cover older complete interactions from the active Run while preserving the newest complete raw tail and current native input.

### 4. Extend the existing session checkpoint to the active Run prefix

Reuse the single session summary/checkpoint and its existing covered Run/record/tool coordinates. Permit the coverage cursor to point into the target Run only when the covered record/tool positions are at or before the operation's frozen committed base and validate to a complete interaction boundary. Request assembly must apply that cursor to both prior history and the active Run's process messages, while always retaining the active Run input as the native user message. Messages and tool facts after the cursor remain raw.

This keeps a single chronological coverage authority. A separate active-Run checkpoint would duplicate summary state and require merging two cutoffs in every request. The existing database columns already represent a Run plus a record/tool cursor; the implementation changes their validation rules and projection use, not the user-facing contract.

### 5. Preserve already-covered prefixes if a Run later ends abnormally

An active Run may be summarized while still running and later end failed or interrupted. Do not attempt to reverse or regenerate an already-installed checkpoint. Keep the terminal outcome and uncovered suffix raw, and prevent later summary selection from crossing unresolved abnormal history. If the abnormal Run had no prior covered prefix, preserve the current behavior: keep it and later process raw and place new coverage before it.

This is necessary because waiting for Run completion would defeat active-Run compaction. Canonical records remain the source of truth, so the summary is still a derived view over a stable prefix rather than an assertion that the entire Run succeeded.

### 6. Freeze active coverage and preserve request identity during recovery

The compaction operation binds the target Run, its base committed record/tool sequences, the exact covered Run/record/tool coordinates, capacity and budgets, summary contract, and prepared summary descriptor. On retry/restart, reconstruct that exact source slice and descriptor; do not widen coverage to later records or reselect against a changed capacity. Commit the new session checkpoint with the existing expected-revision compare-and-swap. If preparation, dispatch, source validation, or the compare-and-swap fails, keep the previous checkpoint and use the existing safe fallback projection.

The Run owner serializes ordinary execution while the summary operation is pending. Stop requests remain observable at current compaction boundaries; stop handling must not install a summary after the target Run has accepted a stop request.

### 7. Re-evaluate after each successful compaction, without trimming in a loop

After installing a checkpoint, rebuild and re-estimate the ordinary request once for the current model action. Do not repeatedly summarize or delete history until an occupancy target is met. If later committed work again takes a prepared request to the threshold, the next model-request boundary can create an incremental operation using the prior checkpoint and newly committed interactions. If the active input or protected raw context alone keeps the request large, preserve it and follow existing Provider preparation behavior.

## Risks / Trade-offs

- [Risk] A checkpoint can now point into a still-running Run, so an incorrect cursor could hide needed context or include an uncommitted result. → Bind the operation to the target's committed base sequences; validate ownership, source refs, and complete interaction boundaries before commit and before projection.
- [Risk] A Run may become abnormal after an earlier prefix was summarized. → Preserve existing covered data, expose terminal outcome and uncovered suffix raw, and block new coverage from crossing unresolved abnormal history.
- [Risk] The indivisible newest interaction, incomplete work, or active input can keep the request above the nominal raw target or context capacity. → Treat `C/10` as an approximate process-selection target; never split, omit, or truncate required content.
- [Risk] Old runtime code rejects checkpoints covering a running Run. → Treat an in-progress active-coverage checkpoint as requiring this implementation for same-Run continuation; keep the checkpoint encoding unchanged and document/test restart and rollback behavior.
- [Risk] A valid summary may not reduce total request size below the trigger because exact inputs, instructions, tools, resources, and the active input are outside the raw-process budget. → Re-estimate the complete request and keep the existing no-silent-truncation behavior.

## Migration Plan

No new table or field is expected: checkpoint and operation records already store covered Run/record/tool coordinates and the active target's committed base. Update Runtime validation to permit same-target coverage only within that base prefix, update Agent selection/request projection to apply the cursor to active process while preserving input, and update the independent summary prompt to describe active source slices. Existing checkpoints continue to represent earlier completed-Run coverage. No canonical Run facts or stored user inputs are migrated or rewritten.

## Open Questions

None. The active Run's committed process is eligible; its exact user input remains preserved; incomplete work remains raw. These decisions follow the user's existing input-retention requirement and the confirmed active-Run compaction goal.
