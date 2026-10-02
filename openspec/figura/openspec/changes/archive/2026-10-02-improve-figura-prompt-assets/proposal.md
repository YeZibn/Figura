## Why

Figura's four static prompt assets establish useful safety boundaries, but give the model too little concrete guidance for choosing evidence, turning observations into chart data, assembling a Figure, and reviewing the rendered result. This change makes those decisions clearer so the model can complete varied chart tasks without forcing every request through the same tool sequence or claiming more than the evidence supports.

## What Changes

- Clarify how the model distinguishes explanation, data extraction, chart reconstruction, user-data visualization, multi-chart composition, and edits to existing results.
- Define what resource metadata, loaded images, OCR, measurements, assembled Figures, and rendered PNGs can support, including their distinct uncertainty and visibility limits.
- Improve observation guidance so selected regions preserve the chart geometry, ticks, category labels, and legends needed for the task.
- Explain how to map supported observations into ChartSpec data, keep unknown values unknown, select measurement references, and follow the current Schema during assembly.
- Add concrete decision guidance for responding to validation failures, inspecting a newly rendered image, correcting a result, or finishing with stated limitations.
- Keep the existing three-layer request structure and four static Markdown assets; do not change tool schemas, runtime state, Provider contracts, or durable execution behavior.

## Capabilities

### New Capabilities

<!-- None. -->

### Modified Capabilities

- `agent-react-execution`: specify the model-facing behavior required of the stable Agent prompt layer when selecting evidence, interpreting observations, assembling charts, and reviewing generated images.

## Impact

- Prompt assets: `src/figura/agent/prompting/assets/agent.md`, `evidence.md`, `workflow.md`, and `response.md`.
- Prompt contract: `openspec/figura/openspec/specs/agent-react-execution/spec.md` through a delta spec.
- Validation scope: review existing prompt asset and Agent request coverage against the new behavior scenarios. Tool contracts, Provider APIs, RunExecutionState fields, image transport, and chart storage remain outside this change.
