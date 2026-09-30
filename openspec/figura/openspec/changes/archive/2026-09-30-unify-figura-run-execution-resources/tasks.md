## 1. Resource Model

- [x] 1.1 Add frozen typed image/tool references and the six resource content variants with only the fields defined in `design.md`.
- [x] 1.2 Replace `RunExecutionState` data fields with exactly `run_id` and ordered `resources`; implement kind-filtered listing and full-reference lookup.
- [x] 1.3 Enforce reference/content kind matching, result/error exclusivity, immutable nested data, and duplicate-reference rejection.

## 2. Resource Reconstruction

- [x] 2.1 Rebuild unique Attachment resources from ordered Run inputs and verify their Sources Session ownership and complete metadata.
- [x] 2.2 Rebuild Panel resources only from committed successful decomposition results whose complete Sources records match the result and Session.
- [x] 2.3 Rebuild OCR and measurement resources from committed tool call, attempt, and result facts; preserve full result, scope, safe failure, and source identity.
- [x] 2.4 Rebuild complete successful ChartFigure resources from persisted assembly arguments and verify the committed digest; retain committed assembly failures as error resources.
- [x] 2.5 Rebuild ChartRender resources from committed results and typed Figure references, preserving complete metadata and safe errors.
- [x] 2.6 Enforce one supplied Run prefix, same-Session authorization, deterministic ordering, and fail-closed behavior for inconsistent committed facts.

## 3. Unified Image Reads

- [x] 3.1 Add the Agent-owned image reader that resolves Attachment and Panel refs only when they exist in the target resource catalog and belong to its Session.
- [x] 3.2 Add transient OCR/measurement annotation reads and ChartRender PNG reads with committed digest, size, media type, and dimension verification.
- [x] 3.3 Make ChartFigure image reads return the bounded explicit-render-required failure; do not invoke rendering during lookup.
- [x] 3.4 Migrate `load_image` and OCR/measurement source resolution to the common typed image reader without changing tool inputs or outputs.

## 4. Tool and Gateway Consumers

- [x] 4.1 Migrate Figure assembly to resolve measurement resources by typed reference and validate committed successful outcomes.
- [x] 4.2 Migrate Figure rendering to load the complete accepted ChartFigure resource and remove its old summary/source-call lookup path.
- [x] 4.3 Migrate Gateway Figure/render summaries to catalog queries while preserving existing public HTTP/SSE field names and private PNG ownership.
- [x] 4.4 Preserve Session-wide Panel listing through its current Sources owner, separate from the target Run catalog.

## 5. Request Assembly and Memory

- [x] 5.1 Build the textual resource index from every catalog kind using stable typed references and concise names/outcomes.
- [x] 5.2 Keep complete tool results only in chronological Memory messages; verify the resource index does not duplicate full result payloads.
- [x] 5.3 Select original, OCR/measurement annotation, and rendered images from the immediately preceding fully committed tool batch through typed references.
- [x] 5.4 Complete authorization, image integrity, annotation reconstruction, and Provider-bound checks before claiming a Provider attempt.

## 6. Regression Coverage and Removal

- [x] 6.1 Cover complete content fields, stable references across Runs, lookup failures, deterministic ordering, repeated observations, and safe failed resources.
- [x] 6.2 Cover current-prefix isolation, later-Run exclusion, Panel commit gating, restart reconstruction, Session authorization, and malformed-success failures.
- [x] 6.3 Cover image reads for every supported kind, explicit Figure rendering, missing/corrupt content, Provider bounds, and latest-batch-only feedback.
- [x] 6.4 Cover prompt inventory completeness and deduplication, Figure/Gateway projections, and unchanged public tool/API contracts.
- [x] 6.5 Delete the six obsolete RunExecutionState collections, summary-only projection types, OCR special reads, and their imports/helpers; confirm no compatibility aliases or callers remain.

## 7. Validation

- [x] 7.1 Run focused Figura state, tool, request, and Gateway regression tests in `conda run -n agent`.
- [x] 7.2 Run the complete Figura Python suite with `conda run -n agent python -m pytest -q` (941 passed; 13 failures in untouched legacy store/Gateway tests).
- [x] 7.3 Run `git diff --check` and search `src/figura` and `tests` for obsolete collection names and old lookup paths.
