## 1. Project the periodic trigger

- [x] 1.1 Derive the current Run's committed ordinary model response count during request assembly and determine when it is a positive multiple of 20; exclude tool work, Provider attempts/retries, context-compaction requests, and earlier Runs.
- [x] 1.2 Add `task_reflection.completed_rounds` and `task_reflection.interval_rounds` to the existing dynamic running-state SYSTEM projection only when due, without adding a durable counter or another request layer.

## 2. Guide task reflection

- [x] 2.1 Update the stable workflow asset to direct the model to recheck the original request, evidence, unmet requirements, recent progress, and next-action value while preserving its choice to continue, correct, or deliver supported results with limitations.
- [x] 2.2 Ensure the periodic cue does not force termination, declare correctness or completion, suppress valid tool calls, require a separate report, or apply to context-compaction requests.

## 3. Verify execution boundaries

- [x] 3.1 Add focused coverage for interval boundaries, one count per committed model response with multi-call batches, excluded attempts/tools/summaries/earlier Runs, and cue omission between intervals.
- [x] 3.2 Verify restart and compaction derive the same cue from an unchanged prefix and Provider retries preserve the frozen request binding.
- [x] 3.3 Verify the reflection policy and dynamic metadata remain in the existing request layer and participate in existing prompt/request identity checks.

## 4. Update documentation and validate

- [x] 4.1 Update the Agent implementation overview and Agent domain document to describe the 20-response reminder, its derivation, and its non-enforcing behavior.
- [x] 4.2 Run the focused Agent request and prompt tests, strict validation for this OpenSpec change, and `git diff --check`.
