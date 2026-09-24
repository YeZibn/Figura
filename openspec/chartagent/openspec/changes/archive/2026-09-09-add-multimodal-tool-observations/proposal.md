## Why

Figura's agent can inspect a user-attached chart and can receive JSON tool
results, but it cannot inspect images produced by those tools. Without feeding
annotated intermediate images back to the multimodal model, the agent cannot
visually verify whether OCR regions or measured bars correspond to the intended
chart elements before accepting, retrying, or replacing a tool result.

## What Changes

- Introduce a normalized tool-result shape that can carry structured data,
  generated image artifacts, captions, and non-fatal warnings while preserving
  compatibility with existing JSON-only tools.
- Extend tool dispatch and the agent loop to return required JSON tool messages
  and then present registered image artifacts as a model-visible multimodal
  observation associated with the originating tool call.
- Add bounded validation and lifecycle handling for generated image artifacts,
  including supported formats, payload limits, per-run ownership, and cleanup.
- Enhance `extract_text` and `measure_bars` to produce visual overlays alongside
  their existing structured results, so the model can inspect OCR boxes, bar
  bounds, indexes, and the detected baseline.
- Keep tool use advisory and freely planned: no fixed extraction sequence,
  mandatory visual-verification step, numeric acceptance threshold, or required
  ChartSpec output is introduced.
- Run all implementation, dependency, script, and test commands through the
  project's Conda environment named `agent`.

## Capabilities

### New Capabilities

- `multimodal-tool-observations`: Normalization, transport, association,
  validation, and lifecycle behavior for tool-generated visual observations.

### Modified Capabilities

- `tool-system`: Tool execution may return normalized structured data plus
  registered visual artifacts while retaining legacy JSON-only results.
- `agent-loop`: The agent feeds tool-generated images back to the multimodal
  model without violating native tool-call message ordering.
- `chart-understanding`: OCR and bar measurement tools provide annotated visual
  evidence in addition to their existing numeric and textual outputs.

## Impact

- Affects the tool result model, registry dispatch contract, Agent history
  construction, multimodal content helpers, OCR and bar geometry tools, and
  their unit/integration tests.
- Requires a provider-compatibility decision for transporting images after a
  native tool response; the implementation must retain a JSON tool message even
  when the provider requires images in a separate multimodal observation turn.
- Adds generated image payloads owned by an Agent run and therefore requires
  explicit validation, retention limits, and cleanup behavior; tools do not gain
  authority to attach arbitrary local paths.
- Adds no new chart type, segmentation model, fixed orchestrator, or mandatory
  reasoning workflow.
