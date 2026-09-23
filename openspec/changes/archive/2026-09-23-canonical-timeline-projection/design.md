## Context

See `proposal.md` for motivation and `specs/` for the observable contract. `ChartReviewManager` is the authoritative review state; `ExecutionGate` is derived. Timeline unit validation already lives in `decision_timeline.py`, while `TraceEmitter` is the event production boundary. The ordinary and evaluation views share `RunTimeline`.

`agent/loop.py` currently coordinates run setup and recovery, prompt context, model turns, tool-call side effects, generated-chart review, checkpoints, and timeline emission. Some low-level responsibilities already live in `turn.py`, `recovery.py`, `measurement_flow.py`, `panel_routing.py`, and `artifacts.py`. The refactor must reuse these boundaries, preserve run behavior, and avoid establishing a second owner for domain or timeline state.

## Goals / Non-Goals

**Goals:**

- Establish one versioned, event-kind-specific contract for timeline correlation and state fields.
- Keep the event log as immutable transition history and the review aggregate as current domain authority.
- Use one frontend user-timeline projection for ordinary and evaluation histories; keep Evaluation diagnostics additive and read-only.
- Make unsupported historical timeline versions explicit without guessing state or deleting stored history.
- Refactor the Agent run orchestration around clear responsibilities while preserving model/tool order, interruption, checkpoint/resume, idempotency, review blocking, and publication behavior.
- Remove only proven redundant or obsolete code in the Agent/timeline path after migrating all repository call sites and tests.

**Non-Goals:**

- Reworking review or measurement domain state, checkpoint semantics, or publication policy.
- Changing the public Agent, Gateway, or client behavior, Gateway routes, Run IDs, event sequence identity, or established public DTO fields.
- Rewriting Evaluation's safe bundle reader, redaction, truncation, resource authorization, or directory containment mechanisms.
- Unrelated repository-wide dead-code cleanup or migration/deletion of old persisted run data.

## Decisions

### 1. Version timeline envelopes and validate by event kind

Advance the timeline correlation envelope from version 1 to version 2 for event kinds that participate in decision-unit projection. Keep existing business event names and identifier/sequence conventions except for the retired Gate mirror events. Define a fixed field set per event kind: for example, `tool_call` uses its running `state`, `tool_result` uses `status`, and review/publication lifecycle events use `state`. Remove same-meaning duplicates such as `tool_result.state`/`tool_status` and `review_subcheck.status`; preserve distinct dimensions such as `review_status`, `candidate_status`, and `publication_status`.

`decision_timeline.py` defines the event-kind contract; `TraceEmitter` and `enrich_event_payload` validate and bound producer payloads before persistence. They reject unsupported or conflicting aliases rather than selecting the first non-empty key. Gateway persistence and replay remain transparent. Gateway DTOs retain their established casing and are not folded into the event schema.

**Alternative considered:** Normalize aliases independently in Gateway and the frontend. Rejected because it creates multiple normalization owners and hides malformed producers instead of fixing them at the source.

### 2. Keep domain state, event history, and query projections separate

`ChartReviewManager` remains the only review-state authority. `ExecutionGate` and the Run summary `executionGate` remain read-only projections and are never used to restore review state. Review transitions are represented by canonical business events; `review_gate_required`, `review_gate_updated`, and nested Gate snapshots are retired. Bounded `review_subcheck` evidence can remain in technical history but does not form a user-facing lifecycle.

The event log records committed transitions; checkpoint serialization continues through the existing recovery boundary. In-memory run context is transient coordination data, not another durable source of truth. Measurement sessions continue to be reconstructed from their checkpoint representation and are not copied into another runtime state store.

**Alternative considered:** Introduce a timeline workflow that owns event state or Gate state. Rejected because it would create a second business-state owner. Event shape validation belongs at the producer boundary; the frontend timeline remains a read-only projection.

### 3. Split orchestration by responsibility, not file size

Keep the public `Agent` construction, `run`, `reset`, `close`, and message-inspection surface stable. Have `Agent.run` delegate one execution to an `AgentRunOrchestrator` with a per-run `RunExecutionContext` for transient state such as messages, layout contexts, artifact references, measurement sessions, selected panel, turn, and pending action. The context is created for one invocation and converted to/from persisted checkpoint data only through the established recovery boundary.

Move the high-level lifecycle of one tool call—gate check, operation journal, dispatch coordination, generated observation handling, trace emission, memory/artifact update, and checkpoint—to a focused tool-execution workflow. Keep `turn.py` responsible for provider turn handling and low-level tool-call preparation/dispatch; keep the existing measurement, panel-routing, artifact, and recovery helpers as their respective owners.

Move generated-chart review orchestration, including post-render review and pending-review resume, into a `GeneratedChartReviewFlow`. It coordinates candidate persistence, deterministic/VLM review, checkpoint callbacks, and trace effects, but delegates all review-state changes to `ChartReviewManager`. It must not maintain its own candidate, repair, publication, or Gate state.

Canonical event shape continues to be owned by `decision_timeline.py` and enforced by `TraceEmitter`; the new orchestration modules call this boundary and do not create a parallel event projector. Extraction must preserve serial tool execution, interruption check points, checkpoint order, fail-closed candidate persistence, and review/publication behavior.

**Alternative considered:** Move the entire `Agent` class into one large runtime module or split helpers mechanically by line count. Rejected because it preserves responsibility tangles behind new filenames and risks changing execution order without establishing ownership.

### 4. Use one user-timeline projection and keep Evaluation diagnosis additive

Retain the existing shared `RunTimeline` rendering path for ordinary runs and evaluation case histories. Tighten its event parser to read only the canonical field defined for each event kind; remove Gate alias lookup and broad status fallbacks. Evaluation continues to produce stage and anomaly diagnostics from saved evidence, but those diagnostics cannot create or rewrite review, measurement, Gate, or publication state. Preserve the reader's size limits, sensitive-field redaction, safe-resource links, and directory containment unchanged.

**Alternative considered:** Move all Evaluation diagnosis into the frontend timeline projector. Rejected because stage diagnosis is evaluation-specific; only user-facing execution-step semantics need to be shared.

### 5. Treat older event history as unsupported, not migratable

The frontend and Evaluation reader support the current version-2 timeline contract only. When a stored timeline contains an unsupported correlation version or invalid event shape, retain the Run/case summary and independently safe details, show an explicit unsupported/unavailable notice, and do not synthesize a legacy unit or success state. Do not modify or delete old persisted data.

**Alternative considered:** Add a Gateway adapter that rewrites version-1 payloads into version 2. Rejected because it would preserve a second event interpretation path and obscure whether old data satisfies the new contract.

### 6. Make cleanup evidence-driven and local to this change

For each proposed deletion, search production code, tests, scripts, frontend, protocol consumers, and persistence readers. Migrate in-repository callers and tests first, then remove obsolete aliases, wrappers, retired event branches, and duplicate projections. Preserve intentional public façades and security/recovery infrastructure; do not treat code as dead solely because it is private or small.

**Alternative considered:** Perform a repository-wide cleanup while touching the main loop. Rejected because unrelated removals would obscure regressions and make the change's verification boundary unmanageable.

## Risks / Trade-offs

- [Older local histories lose their grouped timeline] → Preserve stored data and summary; show an explicit unsupported-version notice rather than deleting records or misrepresenting outcomes.
- [A producer omits a required field and a visible transition is rejected] → Add per-event schema tests; protocol rejection must be bounded and cannot change review, publication, or Run domain outcomes.
- [Removing Gate mirror events leaves live UI stale] → Verify canonical review transitions drive live status and the Run-summary projection is available after hydration.
- [Evaluation details regress while changing event shapes] → Test bounded/deep values, redaction, truncation messages, and authorized resources without relaxing existing limits.
- [Loop extraction changes ordering or resume semantics] → Establish regression coverage before extraction for serial tool calls, interruption boundaries, operation replay, checkpoint round trips, pending-review resume, and publication; compare behavior at each extraction step.
- [Cleanup removes a hidden consumer] → Require reference scans across source, tests, scripts, frontend, protocol and persisted-data readers; migrate call sites before deletion and keep intentional façades.
- [Public consumers depended on duplicate payload keys] → Migrate all in-repository consumers while retaining routes, supported event names, canonical fields, IDs, and ordering.

## Migration Plan

1. Inventory event producers/consumers, Agent responsibilities, state owners, and cleanup candidates; add or identify baseline behavior tests before restructuring.
2. Define the version-2 event-kind schema and update producers/validators together; retire Gate mirror events and duplicate fields while keeping domain outcomes unchanged.
3. Migrate Gateway, frontend, and Evaluation to canonical event fields. Unsupported old histories receive an explicit unavailable state; persisted records are not rewritten or deleted.
4. Extract per-run transient context and high-level tool execution/review workflows from the main loop, reusing existing helper modules and preserving the established public Agent surface and behavior.
5. Complete scoped dead-code cleanup only after reference and test callers have been migrated. Keep Gateway/client façades and Evaluation security boundaries intact.
6. Verify event ordering, reload/reconnect, interruption/resume, idempotency, review blocking/publishing, ordinary/Evaluation parity, and safety bounds before considering this change complete.

## Open Questions

None. The public boundary, state owners, extraction responsibilities, cleanup boundary, and compatibility policy are specified above.
