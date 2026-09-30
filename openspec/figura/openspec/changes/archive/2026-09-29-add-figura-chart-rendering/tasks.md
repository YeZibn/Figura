## 1. ChartFigure renderer

- [x] 1.1 Add a pure Agg-based renderer in `src/figura/charts/chartfigure/rendering.py` for bar, line, scatter, and pie ChartSpec data; preserve chart order, declared columns, labels, axis bounds, and display metadata under the fixed server-side size/style policy.
- [x] 1.2 Add renderer coverage for each chart type, mixed Figures with one to four charts, one- and two-column layouts, PNG dimensions/decoding, and invalid or oversized output.

## 2. Private chart-render storage

- [x] 2.1 Add `src/figura/sources/chart_renders.py` with private storage under the configured Figura data root, a safe filename derived from `(run_id, call_id)`, staged atomic installation, and PNG read validation.
- [x] 2.2 Implement replay behavior for an existing artifact: validate and return the original PNG metadata for the same immutable Run/call, reject corrupted content, and never overwrite the artifact with a second image.
- [x] 2.3 Add storage coverage for file permissions, safe identity derivation, byte/dimension limits, interrupted-write replay, and missing or corrupted files.

## 3. Render tool and derived execution projection

- [x] 3.1 Add `ChartRenderObservation` and `RunExecutionState.chart_renders` in `src/figura/agent/execution_state.py`; rebuild success/failure observations from committed tool facts in Run and call order and verify their Figure references against accepted same-Session Figures.
- [x] 3.2 Add projection coverage for target-Run and prior-Run results, success and structured failure, ordering, and omission of incomplete, malformed, unresolved, or cross-Session references.
- [x] 3.3 Add `render_chart_figure` in `src/figura/tools/implementations/render_chart_figure.py` with an exact Figure-reference input, accepted-Figure lookup, canonical digest verification, renderer/storage orchestration, and the bounded metadata result schema.
- [x] 3.4 Register the tool through `src/figura/bootstrap.py`, update the tool registry version as required, and verify old completed calls remain inert under the existing registry-version rules.
- [x] 3.5 Add tool coverage for current-Run and prior-Run Figure references, unknown/cross-Session references, digest mismatch, render failure, metadata limits, and idempotent replay.

## 4. Agent visual feedback

- [x] 4.1 Extend `AgentRequestBuilder` to add successful render PNGs from only the immediately preceding fully committed batch, in tool-call order, paired with the existing tool result history and current Run/call identity.
- [x] 4.2 Verify image SHA-256, byte count, dimensions, same-Session observation, and Provider image bounds before claiming a Provider attempt; keep historical render inventory textual and do not resend older PNGs.
- [x] 4.3 Add request-building coverage for a successful render batch, multiple renders, old-batch exclusion, missing/corrupted images, and provider-limit failure before attempt claim.

## 5. Figura Gateway output

- [x] 5.1 Extend safe Session and Run-history projections with successful render summaries grouped under the originating Run and joined to the accepted Figure title.
- [x] 5.2 Add the Session-scoped chart-render content route; require Run ownership and committed success, validate PNG metadata, and return the required no-store/nosniff image headers.
- [x] 5.3 Add Gateway coverage for summary projection, valid content reads, cross-Session/unknown IDs, uncommitted files, corrupted content, and response headers.

## 6. Figura frontend preview

- [x] 6.1 Add chart-render DTOs, list/projection typing, and content URL support to the Figura API/client boundary without changing ChartAgent or mock contracts.
- [x] 6.2 Add a read-only chart-render preview grouped by originating Run; load PNGs on demand and keep bytes and local paths out of browser-persisted state.
- [x] 6.3 Add focused UI coverage for multiple renders, empty Sessions, missing Figure titles, and preservation of other frontend modes; run the Figura frontend build and smoke commands.

## 7. Integration verification

- [x] 7.1 Run the relevant Figura renderer, storage, tool, execution-state, Agent-request, Gateway, and frontend checks, then run the repository-required broader validation for affected areas.
- [x] 7.2 Confirm `openspec validate add-figura-chart-rendering --strict --store figura` succeeds and `git diff --check` reports no whitespace errors.
