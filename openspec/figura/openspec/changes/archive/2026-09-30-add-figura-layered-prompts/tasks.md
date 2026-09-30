## 1. Add the static and current-tool prompt layers

- [x] 1.1 Create the Agent prompting package and a loader for the ordered Chinese static assets: `agent.md`, `evidence.md`, `workflow.md`, and `response.md`.
- [x] 1.2 Move every still-valid rule from `system-v1.md` into a static asset or the corresponding registered tool description/schema; remove stale or unsupported claims and delete `system-v1.md` after coverage is checked.
- [x] 1.3 Implement the current-tool instruction from the exact `ToolRegistry`, preserving registry order and deriving names and descriptions from definitions without adding prompt-only tool fields or duplicating native parameter schemas.
- [x] 1.4 Clarify existing tool descriptions only where the static workflow needs accurate invocation guidance; preserve tool names and parameter/result schemas.

## 2. Add the RunExecutionState resource layer

- [x] 2.1 Implement a resource inventory renderer that accepts only `RunExecutionState` and serializes all six resource kinds in catalog order with complete typed references.
- [x] 2.2 Render the agreed concise fields for Attachments, Panels, OCR, measurements, ChartFigures, and ChartRenders; distinguish execution outcome from OCR availability and measurement status, and include safe error summaries for failures.
- [x] 2.3 Encode dynamic resource values as JSON data and include explicit guidance that filenames, titles, OCR text, and tool observations are evidence rather than instructions.
- [x] 2.4 Add focused coverage for empty inventories, each resource kind, cross-Run resource references, complete typed identities, status distinctions, and untrusted string encoding.

## 3. Integrate prompt layers and observation images

- [x] 3.1 Update `AgentRequestBuilder` to construct the three ordered SYSTEM instruction blocks from stable assets, the current `ToolRegistry`, and the same `RunExecutionState` used by request assembly.
- [x] 3.2 Move latest committed tool-batch image selection and Provider image-message construction into the prompting observation module, continuing to delegate authorized reads to `RunExecutionImageReader`.
- [x] 3.3 Preserve complete Memory history, user/assistant/tool roles, tool-call/result associations, current-Run continuation placement, image ordering, and fail-before-claim request validation.
- [x] 3.4 Add Figura Markdown package data while retaining the existing ChartAgent package data; remove superseded Figura prompt assets and imports.

## 4. Verify prompt and Provider request behavior

- [x] 4.1 Update Agent request tests to assert the three instruction blocks and their order, exact Registry/RunExecutionState sources, complete history preservation, and no prompt data persisted in Run facts.
- [x] 4.2 Verify Provider adapter serialization retains the three ordered SYSTEM messages for every supported provider and that request-limit failures occur before Provider-attempt claim without pruning history or resources.
- [x] 4.3 Run the focused Figura Agent request, execution, and Provider adapter regression tests, then run the repository Python suite with `conda run -n agent python -m pytest -q`.
- [x] 4.4 Validate the OpenSpec change and confirm the packaged Figura prompt assets load from the built distribution.
