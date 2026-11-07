## Context

See [proposal.md](proposal.md) for motivation and scope. Agent requests are rebuilt from the current Run's committed facts. The final running-resource SYSTEM block is already a dynamic projection; context compaction uses a separate request purpose, and Provider retries retain a frozen request binding. Tool batches resolve before the next ordinary model request.

The `agent-react-execution` main specification currently prohibits cumulative Run quotas. This change adds a periodic prompt cue while retaining model-controlled continuation and existing terminal behavior.

## Goals / Non-Goals

**Goals:**

- Trigger a task reflection cue after each 20 committed ordinary model responses in the current Run.
- Rebuild the count from the authorized Run facts so restart and compaction do not reset it.
- Keep the cue compact, deterministic, and part of the existing dynamic running-state SYSTEM instruction.
- Guide the Agent to recheck the original request, evidence, unmet requirements, recent progress, and the value of its next action.

**Non-Goals:**

- Enforce a hard Run limit, interrupt execution, require an approval, or create a renewal cycle.
- Add an independent evaluator request, a progress score, a persisted counter, a database field, configuration surface, or public API field.
- Change tool permissions, committed results, resource ownership, Provider retry policy, or context-compaction behavior.

## Decisions

### Count committed ordinary model responses

Count current-Run `MODEL_RESPONSE` records, one per committed ordinary model response. A response containing many tool calls still counts once. Tool invocations, tool outcomes, Provider attempts, transport retries, and context-compaction requests do not increment the count. This measures ordinary decision opportunities rather than physical network traffic or tool volume.

Derive the count from the current `RunState` during request assembly. When the count is a positive multiple of 20, include the cue in the next ordinary request. This produces reminders at rounds 20, 40, 60, and so on without a last-reminded marker. The cue is assembled only after the preceding tool batch resolves, following the existing ReAct boundary. A terminal final response has no following ordinary request and therefore receives no injected cue.

Alternative considered: persist an incrementing counter in Runtime. Recomputing from committed facts avoids migration, counter repair, and duplicate accounting across Provider retries or restarts. The Run state is already materialized for request construction; the initial implementation accepts a linear scan of its committed records.

### Put due metadata in the existing running-state SYSTEM block

Keep the stable workflow policy in `src/figura/agent/prompting/assets/workflow.md`. When due, add a small `task_reflection` object to the existing dynamic running-state JSON, with `completed_rounds` and `interval_rounds` (20). Omit the object on other ordinary requests. Do not add another SYSTEM block, user message, tool result, or Provider call.

The workflow policy directs the model to compare the original request with supported completed work, identify remaining requirements and evidence gaps, consider whether recent actions reduced them, and choose a useful next action. It permits continuing, correcting, or delivering supported partial results with limitations. It does not require a separate report, assert that the task is wrong, declare completion, or force stopping based on round count. Source values and retrieved content remain untrusted data.

Alternative considered: send a dedicated review request to the same or another model. That would add latency and cost and would still make the decision from model judgment. The user selected a simple periodic prompt cue, so reflection stays inside the existing decision request.

### Preserve request binding and auxiliary-request boundaries

The same committed prefix yields the same count and cue after restart or summary compaction. Context-compaction requests do not receive the cue. A Provider retry rebuilds the original logical request from its frozen base prefix and must pass existing fingerprint checks; it does not count the failed physical attempt or recompute from a later Run prefix.

The cue remains part of the assembled instruction content and therefore participates in the existing prompt digest and request identity validation. A changed bound request fails the existing consistency check rather than silently dispatching with a different cue.

### Keep the interval fixed in the first version

Use 20 as the internal interval selected during exploration. Do not add a per-Run setting or environment option in this change. If later evaluation shows that the interval needs adjustment, revise the internal policy deliberately and preserve existing request-binding checks.

Alternative considered: configurable intervals. This would expand the change into configuration validation, request identity, and user-facing policy without current evidence that per-task tuning is needed.

## Risks / Trade-offs

- **The same Agent may overlook the cue or repeat its earlier judgment** → Phrase the reminder around the original goal, evidence, unmet requirements, and next-action value; evaluate behavior on both incorrect-progress and valid long-task traces. The cue is guidance, not a correctness guarantee.
- **A fixed interval may be too late for short failure loops or too frequent for long tasks** → Start at the user's chosen 20 rounds and assess it with representative Run traces before changing the interval.
- **Counting scans more records as a Run grows** → Reuse the already-loaded committed `RunState` and avoid additional persistence or queries; revisit only if profiling shows material request-assembly cost.
