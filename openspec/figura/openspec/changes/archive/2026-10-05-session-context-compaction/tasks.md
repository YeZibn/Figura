## 1. Source references and durable context checkpoint

- [x] 1.1 Define typed references for Session messages and generic tool results, reusing existing typed resource references where applicable; validate ownership against the target Run's authorized prefix when checkpointing or retrieving references.
- [x] 1.2 Add durable Session context-checkpoint storage with source frontier, revision, summary contract version, and source references; verify atomic replacement, restart reconstruction, and Session deletion cleanup.
- [x] 1.3 Add durable internal compaction-operation state and bind the selected summary revision or fallback decision to ordinary Provider request retries; verify interrupted and repeated operations preserve request identity.

## 2. History and resource retrieval

- [x] 2.1 Implement read-only history/resource search over validated Run records, tool facts, abnormal outcomes, and resource metadata with filters, excerpts, and continuation cursors; verify later Runs and other Sessions are excluded.
- [x] 2.2 Implement exact message, tool-result, and typed-resource reads with optional field/range selection; verify full default results, structured failures, unknown outcomes, and no historical tool re-execution.
- [x] 2.3 Add a typed historical-image read tool backed by `RunExecutionImageReader`; verify Attachment, Panel, OCR/measurement annotation, and ChartRender paths while preserving the existing `load_image` contract.
- [x] 2.4 Register retrieval tools and mark their returned content as untrusted historical data; verify retrieval calls use the current Run audit/replay path and cannot select another Session.

## 3. Context compaction and request projection

- [x] 3.1 Implement complete-interaction boundary selection and a source-linked summary contract that preserves recent history, current Run input, provider continuation requirements, and abnormal outcome classifications.
- [x] 3.2 Implement summary request preparation with the selected Provider/model, structured response validation, reference verification, and atomic checkpoint commit; verify failure leaves the prior checkpoint unchanged.
- [x] 3.3 Update request assembly to combine a validated summary checkpoint with the protected recent raw tail and a compact resource locator projection; verify `RunExecutionState` remains complete for server-side listing and lookup.
- [x] 3.4 Integrate the approximately 80% trigger before ordinary Provider-attempt claim, re-estimate after compaction toward approximately 50%, and fall back to the uncompressed request when summary generation fails and existing validation permits it.
- [x] 3.5 Verify ordinary Provider retries reuse the exact compaction checkpoint or fallback decision and preserve the existing request fingerprint, continuation pairing, and payload/protocol failure behavior.

## 4. Regression verification

- [x] 4.1 Add focused tests for configured/unknown capacity, unavailable estimates, threshold crossings, best-effort target occupancy, and preservation of complete canonical history.
- [x] 4.2 Add retrieval tests for message/tool/resource references, pagination, cross-Session and future-Run rejection, abnormal outcomes, prompt-injection labeling, and historical image integrity.
- [x] 4.3 Add recovery tests covering summary-operation failure, interruption before checkpoint commit, checkpoint reuse after restart, and ordinary Provider retry stability.
- [x] 4.4 Run the relevant Python test suites and `openspec validate session-context-compaction --type change --store figura --strict`; resolve all failures before marking the change ready to apply.
