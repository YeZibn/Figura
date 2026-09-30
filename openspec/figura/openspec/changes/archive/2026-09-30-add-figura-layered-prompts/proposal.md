## Why

Figura currently keeps stable Agent policy in one Markdown file while tool descriptions, Run resource summaries, complete conversation history, and observation images are assembled in `AgentRequestBuilder`. This makes prompt responsibilities hard to review and update, and makes it easy for instructions to drift from the registered tools or the current `RunExecutionState` contract.

This change gives the Agent prompt a clear three-layer structure while preserving the existing ReAct request, complete Session history, typed Run resources, and transient image feedback.

## What Changes

- Replace the single `system-v1.md` asset with Chinese Markdown assets for stable Agent responsibilities, evidence rules, workflow, and final responses.
- Generate the current-tool layer from the exact `ToolRegistry` used to create Provider tool schemas; keep each tool's native JSON Schema as the parameter authority and improve the existing descriptions where needed.
- Generate one factual resource inventory from `RunExecutionState`, covering attachments, panels, OCR results, measurements, ChartFigures, and chart renders with their complete typed references and concise status summaries.
- Extract request-time prompt loading, tool rendering, resource rendering, and latest-batch image feedback into focused Agent prompting modules. Keep `AgentRequestBuilder` responsible for coordinating these projections, complete Memory history, provider continuations, and request validation.
- Preserve full chronological Session messages and tool results. Keep original, annotated, and rendered image feedback scoped to the immediately preceding committed tool batch and preserve current pre-dispatch Provider-limit validation.
- Package the new Markdown assets and remove the superseded single-file prompt.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `agent-react-execution`: Define the three ordered SYSTEM instruction blocks, their source-of-truth boundaries, while retaining complete history and current image feedback behavior.

## Impact

- Affects `src/figura/agent/request.py`, new modules under `src/figura/agent/prompting/`, Chinese prompt assets, package-data configuration, and the existing Agent request specification and regression tests.
- Does not add fields to `RunExecutionState`, alter Memory retention, introduce prompt truncation or summarization, add a review state, or change Provider APIs, tool names, or tool parameter/result schemas. Existing tool descriptions may be clarified to keep invocation guidance aligned with the registered tool surface.
- The tool-callable `load_image` remains limited to Attachment and Panel resources. Historical OCR, measurement, and render images are not made explicitly reloadable by this prompt change.
