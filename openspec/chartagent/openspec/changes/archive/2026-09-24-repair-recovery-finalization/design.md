## Context

See `proposal.md` for motivation and `specs/` for the behavior contract. The current recovery reader validates a child cursor against a flattened parent-plus-child prefix, although `entry_cursor` is local to each Run. The model-response commit already uses the `final` action for a no-tool response, but the later guarded `final_answer` commit advances the cursor back to `model`. Gateway publishes the final answer and marks the Run complete after Agent execution returns, leaving that cursor able to reissue the model after a crash. The final-answer guard also reduces all verification statuses to one global set. In `ToolExecutionFlow`, truncating the artifact list by rebinding a local variable detaches it from the Agent execution context.

Run statuses, checkpoint action kinds, entry kinds, parent references, and the public `runId:sequence` event identity remain unchanged. Parent Run prefixes are immutable; each child owns its local entry sequence and references a parent cursor.

## Goals / Non-Goals

**Goals:**

- Validate every Run's local entry prefix and every parent cursor before flattening a lineage.
- Preserve a committed final answer as the next action through recovery and terminal completion, without another model request.
- Evaluate answer claims against their referenced artifact or the current output scope, not unrelated historical attempts.
- Keep bounded artifact records attached to the shared Agent execution context across an ordered tool batch.
- Add fault and regression coverage for the four behaviors.

**Non-Goals:**

- Do not introduce a compatibility adapter, old-format fallback, duplicate lifecycle state, or storage migration.
- Do not refactor the seven runtime callbacks, make verification storage canonical, clean unrelated dead variables or duplicate artifact production, or split `verification/flow.py`; those belong to the separate verification-convergence change.
- Do not change public Run/SSE fields, event identity, terminal state names, or resume child attribution.

## Decisions

### Validate local cursors before building a flattened prefix

Keep `entry_cursor` local to its Run. Validate the current Run's own entries against that cursor, then recursively validate each immutable `parentRunId`/`parentCursor` edge, including bounds, completeness, cycle detection, and the existing lineage depth limit. Flatten the validated entries only for reconstructing model context. Remove the comparison between flattened entry count and the current Run's local cursor.

This preserves ownership and sequence meaning across `resume → child → resume`. Changing child cursors to store flattened counts would mix parent and child sequences and require rewriting cursor semantics. Invalid ancestry continues to fail closed with the existing bounded unavailable reason.

### Keep the existing `final` action active after answer commit

The no-tool model response is already durably committed with a `final` cursor. Keep that behavior so a crash before final-answer processing can reuse the committed response. After guarding the response and committing the final answer, advance the cursor to `final` referencing the newly committed final-answer entry instead of `model`.

The existing final-action resolver will read the entry named by its cursor: a committed model response is the candidate to guard and commit; a committed final-answer entry is the exact guarded answer to reuse. The resumed child commits its own final-answer fact with a `final` cursor, returns the same answer, and lets Gateway complete that child. This makes each interruption boundary recoverable without adding an action kind or status. Repeated finalization uses the existing work identity and per-run terminal/event guards so it does not issue another model request or duplicate a final event within that Run.

An alternative was to add a new finalization state or preserve `model` as a fallback after answer commit. The former adds another lifecycle state; the latter recreates the model-call crash window. Neither is needed with the existing `final` action.

### Scope final-answer checks to the answer's outputs

For an answer containing an explicit artifact ID, validate that artifact's exact promotion and verification references. For a generic chart claim, use the Agent's bounded current output artifact records and the matching committed verification facts. In a collection, preserve every current child outcome; a generic success claim is allowed only when its current output scope supports it. If there is no current matching result, fail closed for the claim. Verification failures from older attempts outside that scope do not add a disclaimer or reject a later successful result.

This replaces the global set of all historical statuses. It uses current execution context and existing artifact/verification identities rather than adding a persisted “current attempt” flag or parallel lifecycle field. Specific artifact claims remain tied to their own attempt even when another attempt succeeded.

### Preserve shared artifact-list identity when applying the bound

After adding artifacts from each tool call, trim the existing shared list in place to its latest 48 records. The next model turn then sees records from every call still inside the bound. Keep the bound and record format unchanged; do not add a second index or deduplication behavior in this change.

### Verify the crash boundaries directly

Add regression cases for a three-generation resume lineage, a malformed ancestor, interruption after model-response commit, interruption after final-answer commit but before Gateway completion, and retries of final publication. Add final-guard cases for fail-then-pass and pass-then-fail histories, exact references to both attempts, and mixed collection children. Add a multi-tool batch case that checks the next prompt receives artifact records from all calls within the bound, plus a bound-trimming case.

Use the existing Python test suite and temporary Gateway stores. Do not introduce an external dependency or a new state compatibility suite.

## Risks / Trade-offs

- A corrupt or cyclic parent chain remains unavailable rather than partially recoverable → Validate every local prefix before any Agent execution and retain bounded cycle/depth checks.
- Final-action recovery may be interrupted repeatedly → Keep the cursor on the committed final answer, make final-answer commit and terminal publication idempotent per Run, and test interruption on both sides of the commit.
- A generic answer may refer ambiguously to multiple charts → Scope it to all current output records, preserving collection-child outcomes; require an exact artifact result for specific claims.
- Artifact context remains bounded → Preserve the existing 48-record policy and test that truncation mutates the shared context consistently.

## Migration Plan

No database schema or public protocol migration is required. Deploy the code and specs together; existing in-flight model-response final cursors remain recoverable through the current `final` action, and new final-answer commits keep that action instead of returning to `model`. Restarted active Runs remain interrupted under the existing lifecycle and can be explicitly resumed. If rolling back code, resume Runs created after deployment with the same code revision because the final-action cursor now points at the committed final-answer entry.
