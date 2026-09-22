## 1. Establish the strict event contract

- [x] 1.1 Define the canonical timeline event envelope and validation rules for `unit_id`, `unit_type`, `phase`, `actor`, `role`, `state/status`, `transition_id`, `call_id`, `review_id`, candidate, and attempt references.
- [x] 1.2 Update the Python event normalization and trace boundary to validate the new envelope, remove `legacy`/`unknown` inference, and reject malformed timeline events with bounded protocol errors.
- [x] 1.3 Update every runtime event producer, including tool execution, measurement, generation, review, publication, run lifecycle, and Gateway persistence paths, so related events share one canonical unit identity and call/review identity.
- [x] 1.4 Remove `legacy_envelope`, compatibility identity generation, and any producer path that emits a timeline event without complete semantic metadata.

## 2. Make review lifecycle canonical

- [x] 2.1 Make the review coordinator the sole owner of generated-candidate review transitions and ensure one candidate attempt uses one review identity from start through publication.
- [x] 2.2 Remove `chart_review_started` and `chart_review_completed` production, stream, reader, protocol, and display paths; keep deterministic/VLM subchecks only as diagnostic details.
- [x] 2.3 Route internal candidate review results back into the canonical review record instead of creating a second review unit or review identifier.
- [x] 2.4 Align publication events and review gate updates with the canonical review lifecycle, preserving blocking, repair, retry, collection-parent, and publication semantics.

## 3. Replace the frontend timeline projection

- [x] 3.1 Replace the separate user-facing `ToolStep` and `DecisionUnit` projections with one `TimelineNode` model keyed by canonical `unit_id`, retaining raw events and authorized technical details on the node.
- [x] 3.2 Implement one ordered status reducer for tool calls/results, measurement observations, generation, review, publication, interruption, and history gaps; ensure an authoritative successful tool result promotes the node out of running or unknown state.
- [x] 3.3 Remove frontend legacy/unknown types, compatibility buckets, legacy IDs, tool-name/sequence fallback matching, and all user-facing unknown status fallbacks.
- [x] 3.4 Consolidate lifecycle labels into one Simplified Chinese catalog; show raw English kinds only inside technical JSON and remove the generic “业务步骤” presentation.
- [x] 3.5 Ensure ordinary runs and evaluation history render the same TimelineNode projection, including one review card, one generated result status, failure reasons, and expandable technical details.

## 4. Rewrite protocol fixtures and regression coverage

- [x] 4.1 Replace decision-timeline, review-gate, Gateway, evaluation, and chart-review fixtures with the strict canonical event shape; remove tests that assert legacy envelopes or compatibility aliases.
- [x] 4.2 Add Python contract tests covering complete event metadata, malformed-event rejection, shared review identity, absence of `chart_review_*`, publication gating, replay idempotency, and collection/attempt lineage.
- [x] 4.3 Add frontend timeline regression coverage using the actual explicit-unit payload shape from the reported run; assert Chinese labels, review-in-progress/final states, one review cycle, and completed generation after `tool_result.success`.
- [x] 4.4 Remove smoke checks and source assertions that require `legacyUnitId`, `compatibilityBucket`, compatibility labels, or duplicate review event support.

## 5. Clean local data and verify the breaking migration

- [x] 5.1 Remove or regenerate local runtime/evaluation fixtures that use the retired event protocol, keeping only strict-protocol samples for development and evaluation.
- [x] 5.2 Update the affected main OpenSpec specifications from the completed delta and validate that the implementation, protocol, and user-facing timeline contract agree.
- [x] 5.3 Run targeted Python and frontend timeline tests, then run the full Python suite, frontend build/smoke checks, strict OpenSpec validation, and `git diff --check`.
