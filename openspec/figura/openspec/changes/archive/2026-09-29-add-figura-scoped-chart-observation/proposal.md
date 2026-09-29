## Why

Figura's bar, line, and scatter measurement tools analyze the complete selected image, so unrelated chart marks and labels can interfere with detection. OCR currently supports measurements internally but has no authorized standalone tool, and Figura has no pie measurement capability. This change brings scoped text and chart observation into the same Run-safe tool flow.

## What Changes

- Add one optional `observation_scope` input to `extract_text` and all four chart measurement tools. The bounded include/exclude polygons use normalized coordinates relative to the selected Attachment or Panel; omitting the field means the full source.
- Add the authorized `extract_text` OCR tool that returns bounded text snippets, source-coordinate boxes, confidence, availability, and truncation status.
- Add `measure_pie` for ordinary 2D circular pie charts, returning sector geometry and ratios only when coverage evidence supports them.
- Apply the selected scope to geometry detection and OCR association across bar, line, scatter, and pie measurements; keep returned geometry in the selected source's pixel coordinates.
- Feed committed OCR and pie results back as transient annotated images in the next model request, and include pie results in the existing Run measurement projection.
- Keep scope requests in existing tool-call facts and results in existing tool-result facts. Add no scope store, OCR state, image endpoint, or frontend control.

## Capabilities

### New Capabilities
- `ocr-text-observation`: authorized, bounded OCR extraction with optional observation scope.
- `pie-chart-measurement`: source-bound 2D pie geometry and gated sector ratios.

### Modified Capabilities
- `bar-chart-measurement`: accept and apply an optional observation scope.
- `line-chart-measurement`: accept and apply an optional observation scope.
- `scatter-chart-measurement`: accept and apply an optional observation scope.
- `agent-react-execution`: include committed OCR and pie visual feedback in the next model request and project pie results with other measurements.

## Impact

Affected code includes Figura's tool schemas and adapters, measurement sensors, OCR and visualization helpers, tool Registry, `RunExecutionState`, Agent request assembly, and system tool guidance. The Registry version changes. No external dependency, durable storage schema, Gateway route, or frontend protocol change is intended. Existing measurement contracts change from full-source-only analysis to full-source-by-default with an optional validated scope.
