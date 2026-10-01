## Context

See `proposal.md` for the problem and scope. Session history is already reconstructed from complete prior Run facts, and each `RunState` read includes its `provider_continuations`. `SessionHistory` projects normalized messages without continuation. The request builder currently indexes only the target Run's continuation facts and attaches them only to assistant messages from that Run. Provider payload validation happens inside `ProviderClient.complete`, after the executor has claimed a durable Provider attempt.

## Goals / Non-Goals

**Goals:**

- Let provider request assembly use a continuation only for the exact assistant response that produced it, including responses from earlier Runs in the same Session.
- Keep continuation source-owned, provider-private, and absent from neutral history, persistence changes, and public surfaces.
- Finish deterministic Provider request validation and payload construction before writing a Provider attempt, while ensuring dispatch still follows a committed claim.
- Preserve complete-history and no-retry behavior when the selected Provider cannot accept the historical conversation.

**Non-Goals:**

- Add Session-level continuation storage, continuation copying, a database migration, or a compatibility representation.
- Prune or summarize history, fabricate missing continuation, switch Provider/model, disable thinking, or resend an unresolved attempt.
- Change frontend controls, public API/event fields, prompt content, or continuation visibility.
- Redefine provider-specific continuation rules. DeepSeek's existing requirement remains policy-owned; the same request preparation path also keeps the existing MiMo policy behavior intact without claiming an additional upstream contract.

## Decisions

### Resolve continuation by its source Run and response

Build a request-local index from continuation facts in the target `RunState` and all supplied prior `RunState` values. Key the index by `(run_id, response_record_id)`, then look up each projected assistant message using its own source identity. Reject duplicate or internally inconsistent source keys as a bounded local integrity failure. Do not modify `MemoryMessage` or `SessionHistory`.

Attach the exact stored continuation only when its Provider identity matches the target Run's selected Provider. Keep its format version and reasoning content unchanged. Provider policy validation decides whether the format is supported and whether a continuation is mandatory for the particular request. A mismatched Provider continuation is not sent; if the selected Provider requires one for that assistant message, its preparation fails closed.

**Alternative considered:** Put continuation into `SessionHistory` so all downstream messages carry it. Rejected because that would make neutral conversation memory Provider-specific and blur source-Run ownership.

### Prepare once, claim, then dispatch the same request

Split the local and remote phases of the existing Provider client:

1. Build the `ProviderRequest` using complete Session history and source-scoped continuation facts. Keep mapping and integrity checks here; move generic Provider request validation out of request assembly so it has one owner.
2. Create the explicitly selected Provider client and prepare the call. Preparation performs model/request validation and the Provider policy's payload construction, including continuation requirements. It performs no transport request.
3. If preparation fails, commit the Run's existing bounded terminal failure without creating a Provider attempt or provider-attempt outcome. Do not persist or expose prompt, payload, continuation, credentials, or provider rejection text.
4. Under the per-Run execution lock, re-read the Run and confirm its status, checkpoint revision, and next action still match the snapshot used to build the request.
5. Atomically claim the Provider attempt. If the claim fails, discard the prepared call and do not dispatch.
6. Dispatch the already-prepared call once, then use the existing response/failure commit paths.

Represent the prepared call as a small private, non-serializable value owned by `ProviderClient`, with its payload and original request excluded from its representation. This avoids rebuilding the payload after the durable claim and keeps transport payload details out of Agent and Runtime state. No prepared value is persisted. The client API is internal to Figura; update its callers and tests directly rather than retaining an old `complete(request)` compatibility path.

**Alternative considered:** Build the payload before claim, discard it, and call the current `complete(request)` after claim. Rejected because it would validate/build twice and would not prove that the exact prepared payload is the one dispatched. Claiming before payload construction is also rejected because local incompatibility would still create a misleading started attempt.

### Preserve selected-Provider and recovery boundaries

Provider selection remains a property of each Run. When historical continuation is incompatible with the selected Provider, preserve all history and fail local preparation; do not silently reroute the Run. When the durable claim has committed, existing recovery semantics remain unchanged: an unresolved started attempt becomes outcome-unknown and is never replayed.

No persistent model changes are needed. Existing continuation facts remain attached to their source response and are already loaded with prior Run state. Public projections continue to use the existing allowlisted event and error data.

## Risks / Trade-offs

- **[An earlier assistant response lacks continuation required by the selected Provider] →** Fail during local preparation before attempt claim; retain the complete history and report the existing bounded Run failure.
- **[A continuation is associated with the wrong assistant response] →** Use the composite source identity `(run_id, response_record_id)`, validate uniqueness, and cover multiple prior responses in request assembly tests.
- **[Concurrent progress makes the prepared request stale] →** Re-read and compare the checkpoint revision and action under the execution lock before claiming; discard stale prepared values.
- **[Prepared payload accidentally appears in diagnostics] →** Keep it private and non-serializable, suppress content-bearing representation, and do not add payload logging or public event fields.
- **[The attempt claim commits but dispatch does not occur before a process failure] →** Preserve the established unknown-outcome rule and do not retry; this change does not weaken durable execution safety to recover a local/network ambiguity.

## Migration Plan

No database or persisted Run format migration is required. Deploy the code and spec changes together; existing continuation facts remain readable. Rollback consists of reverting the code change and does not require data repair because no stored shape changes. Runs failed under the previous behavior remain terminal and are not automatically replayed.
