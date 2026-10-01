## 1. Runtime progress events

- [x] 1.1 Add `run_progress` to the Runtime event kind and strict event codec with exactly one bounded `checkpoint_revision` payload field.
- [x] 1.2 Append one progress event atomically with model-response tool-call batches, new tool-attempt starts, replay-attempt starts, and committed tool results.
- [x] 1.3 Migrate the SQLite event-kind constraint to accept `run_progress` while preserving existing event rows, sequences, and immutability triggers.
- [x] 1.4 Update Run-state validation to allow ordered progress events between creation and the optional terminal event while continuing to accept existing lifecycle-only Runs.
- [x] 1.5 Add Runtime regression coverage for each progress transition, event ordering, migration preservation, and rollback leaving no marker or partial checkpoint/fact change.

## 2. Gateway timeline projection

- [x] 2.1 Add a thread-safe `RunDispatcher` query that reports whether the current Gateway owns a Run execution.
- [x] 2.2 Build ordered per-Run timeline summaries from `ToolCallFact`, attempt facts, and result facts, deriving pending, running, reconciliation-required, unknown, completed, failed, and not-started states without inferring success.
- [x] 2.3 Add per-tool allowlisted detail summaries for currently supported Figura tools, including attempt timestamps and safe error summaries; make unknown tools fall back to identifier, status, and timestamps only.
- [x] 2.4 Add Session-scoped snapshot and single-call detail routes, checking Session, Run, and call ownership and returning bounded not-found errors for foreign or unknown calls.
- [x] 2.5 Add the on-demand OCR/measurement observation PNG route using `RunExecutionStateService` and `RunExecutionImageReader`; verify the committed result and authorized source, and return no-store image headers without writing a file.
- [x] 2.6 Project `run_progress` in history and SSE with the existing `runId:sequence` event identity, expose only the committed checkpoint revision, and keep the stream open until a terminal event.
- [x] 2.7 Add Gateway regression coverage for safe projections, ownership checks, status derivation, event replay, and observation image authorization.

## 3. Figura client API and event refresh

- [x] 3.1 Add typed Figura timeline snapshot/detail DTOs and client methods for snapshot, per-call details, source references, and observation images.
- [x] 3.2 Subscribe to `run_progress` in Figura mode and refresh the durable snapshot while preserving the existing event cursor and deduplicating by Run ID plus call ID.
- [x] 3.3 Add client coverage for reconnect/reload snapshots and ensure ChartAgent and mock adapters never call the Figura timeline routes.

## 4. Figura timeline presentation

- [x] 4.1 Add a Figura timeline view model that maps safe DTOs to localized tool labels and statuses without synthesizing legacy `AgentRunEvent` values.
- [x] 4.2 Render one flat row per tool call with visible identity, time, status, and safe summary; keep attempt and tool-specific details collapsed by default and fetch them only when expanded.
- [x] 4.3 Load authorized source images through existing attachment/Panel routes and OCR/measurement overlays through the new observation route; keep Panel and ChartRender galleries in their existing locations.
- [x] 4.4 Add or update frontend smoke coverage for completed, active, failed, unresolved, and unknown timeline rows and unchanged mock/ChartAgent behavior.

## 5. Integration verification

- [x] 5.1 Run the targeted Figura Runtime and Gateway pytest suites in the `agent` Conda environment, then run the full Python test suite.
- [x] 5.2 Run `npm run build` and `npm run smoke` from `frontend/` and resolve any failures related to Figura timeline integration.
- [x] 5.3 Run `git diff --check` and confirm the change introduces no duplicate timeline persistence, raw tool payload exposure, or changes to ChartAgent/mock contracts.
