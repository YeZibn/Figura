## Context

See `proposal.md` for the motivation. The current generated-review flow has two mutable representations: `ChartReviewManager` owns candidate/review/publication fields, while `ReviewCoordinator` owns review records and a run gate. The Agent reads the manager for prompt context and the coordinator for enforcement. The Gateway already stores unpublished candidate image bytes and publishes them only through an identity-checked promotion operation; the Agent currently reaches that persistence sink after review completes.

The `review-gates` delta defines generated-review state as the only review lifecycle. Measurement observations remain evidence and do not enter this lifecycle.

## Goals / Non-Goals

**Goals:**

- Make `ChartReviewManager` the single owner of mutable generated-review aggregates, including candidate status, deterministic and VLM results, repair lineage, publication status, and idempotency.
- Derive every execution-gate view from the manager's current aggregates.
- Execute deterministic artifact checks once per candidate review and apply their result together with the optional VLM result.
- Persist a candidate's review input before external review work so an interrupted review can resume against the same candidate and identity.
- Keep the current client event and artifact projection shape while making those values read-only projections of canonical state.

**Non-Goals:**

- Change the VLM review prompt, review criteria, attempt limits, repair policy, source-scope policy, or publication rules.
- Change how the main Agent decides which measurement evidence to use or whether to run a targeted measurement.
- Redesign the frontend timeline or the evaluation report format; those consumers continue receiving the existing canonical review events and derived projections.

## Decisions

### The manager owns the generated-review aggregate

Evolve `ChartReviewManager` into the sole mutable store for generated candidates and their review lifecycle. A candidate aggregate keeps one candidate ID and review ID across deterministic checks, VLM review, repair classification, and publication. Candidate lineage creates a new aggregate only when a new render attempt creates a new candidate.

`ReviewCoordinator`, `ReviewRecord`, `ReviewDecision`, and `GeneratedChartReviewAdapter` will no longer represent generated-chart state. Remove the generic measurement adapter and its exports because measurement quality is not a review subject in the chosen contract and the adapter has no production caller. Keep a small immutable `ExecutionGate` projection type only if API serialization needs it; do not keep a gate cache or a second transition store.

**Alternative considered:** Make `ReviewCoordinator` authoritative and strip lifecycle fields from `ChartCandidate`. It already serializes review records, but would require the candidate manager to proxy all lifecycle data through generic review records and preserve the current adapter-shaped split. The generated-domain manager already owns the candidate payload, lineage, and publication decision, so consolidating transitions there leaves one domain owner and removes the mapping layer.

### Gate and event data are projections

The manager computes the run gate from the set of non-superseded candidate aggregates. Any pending, repairing, failed, or exhausted candidate keeps publication and successful termination blocked. Passed candidates open their own publication transition; collection parent state is computed from its children. Prompt context, tool-call authorization, terminal checks, checkpoint summaries, and Gateway projections must call the same gate projection function.

Review lifecycle events are emitted from aggregate transitions. Keep one visible start and one final outcome per candidate review identity; deterministic and VLM check details may remain in bounded technical trace data but do not create extra lifecycle identities. Preserve current external review and generated-artifact payload field names during this change; field unification belongs to a separate protocol change.

**Alternative considered:** Rebuild status independently from event history in the Agent, Gateway, and frontend. This repeats the current drift risk and makes event replay a second state machine, so event history remains an audit stream while the manager owns live transitions.

### Run the deterministic audit once

The review operation produces one deterministic safety result and passes that exact result to the final review transition. If it blocks the candidate, semantic VLM review is skipped as today. Otherwise, the required tool-free VLM call runs once. The manager merges the two results, validates candidate/review/digest identity, and commits the final candidate state atomically. The Agent coordinates the VLM request and trace emission but does not independently recalculate safety or mutate review state.

**Alternative considered:** Keep the deterministic call in both the Agent and `ChartReviewManager.process()` and attempt to make it idempotent. The check is pure but potentially expensive, and duplicate execution already produces duplicate trace details; sharing its immutable result is simpler.

### Persist candidate input before review and checkpoint only canonical state

Stage each rendered candidate in the existing private generated-candidate artifact store before deterministic/VLM review begins. Store the immutable rendered bytes and the ChartSpec needed to re-evaluate that candidate alongside its stable candidate/review IDs and digest. Review state checkpoints contain one versioned manager snapshot referencing those stored inputs; they do not persist a second `executionGate` state. The Gateway run summary may continue to cache the derived gate for reads, but it is refreshed only from manager transitions and is never used to restore authority.

On recovery, hydrate the manager snapshot, resolve its candidate inputs from the private artifact store, and derive the run gate. If a referenced candidate or ChartSpec is unavailable or its digest does not match, mark recovery unavailable and keep publication closed. Do not rerender, silently skip review, or infer a pass.

**Alternative considered:** Put image bytes in checkpoint JSON or rely on event history alone. Checkpoints would become large and duplicate private binary data; event history is an audit interface and may be bounded. The private candidate store already owns candidate bytes, so it is the appropriate payload boundary.

### Treat the checkpoint change as a clean break

Write a new explicit review-state version. Do not read the old `reviewState.records` plus `executionGate` shape or fall back to a standalone gate. If a resumable run contains only the old split state, return a bounded unsupported-state recovery error and keep the candidate unpublished. Historical completed runs and their event/artifact records remain readable; they are not migrated into active review state.

**Alternative considered:** Keep a dual reader or a conversion branch indefinitely. The user has chosen to remove compatibility layers, and preserving old active checkpoints would retain the exact second state representation this change removes.

## Risks / Trade-offs

- [Candidate staging may fail before review begins] → Treat persistence failure as a review failure, emit a bounded error, and never publish or claim success.
- [Collection child aggregation may change gate selection] → Preserve current parent/child semantics and cover pending, mixed pass/fail, retry, and superseded-child cases with manager-level regression tests.
- [Old interrupted runs cannot resume after the checkpoint format change] → Return an explicit error without deleting their stored history or artifacts; new runs use only the canonical snapshot.
- [Gateway's cached gate could drift from manager state] → Update the cache only from the aggregate transition callback and verify the projection against a fresh manager computation in lifecycle tests.
- [Candidate metadata might accidentally expose private chart inputs] → Persist bytes and ChartSpec only in the existing private artifact boundary; checkpoints and events contain bounded opaque references and digests.

## Migration Plan

1. Move review state transitions and gate calculation into `ChartReviewManager`; remove generated-review adapter/coordinator state and unused shared review adapters.
2. Add a versioned manager snapshot and candidate-store rehydration. Remove old split-state restoration and fail closed for unsupported active checkpoints.
3. Stage generated candidates before review; update the final candidate state and promote to a published artifact only after the canonical review transition passes.
4. Keep existing external event/artifact projections, deriving them from manager transitions. Remove tests that assert coordinator internals and replace them with aggregate, idempotency, recovery, and publication invariants.

Rollback is a code rollback only: a previous runtime cannot resume runs that already wrote the new checkpoint version. Preserve those run records and artifacts; resume them only with a runtime that understands the new version.
