## Why

Four consumer specifications still describe removed `RunExecutionState` fields such as `available_attachments`, `panels`, `chart_figures`, and `chart_renders`. The implementation now exposes those inputs and committed tool outcomes through one typed `resources` catalog, so the consumer specs need to match the current contract and the `run-execution-resources` specification.

## What Changes

- Update the bar-measurement and OCR specs to describe resolving Attachments and Panels by typed image references in the Run resource catalog.
- Update the Figure-assembly and rendering specs to describe committed Figure and render outcomes as typed tool resources, including the existing prompt summary projection.
- Preserve the current tool inputs, result contracts, authorization rules, and runtime behavior; this is a specification alignment only.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `bar-chart-measurement`: describe source authorization through typed Run resources.
- `ocr-text-observation`: describe source authorization through typed Run resources.
- `chart-figure-assembly`: describe accepted Figures through typed resources and the current prompt summary.
- `chart-rendering`: describe render outcomes through typed resources and their current inclusion rules.

## Impact

Only the four listed OpenSpec capability specs and this change's planning artifacts are affected. No application code, API, persistence format, or runtime behavior changes. The shared resource contract remains owned by `run-execution-resources`.
