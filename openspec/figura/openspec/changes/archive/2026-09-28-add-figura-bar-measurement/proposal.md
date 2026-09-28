## Why

Figura can identify and load authorized Attachments and Panels, but it cannot yet return structured measurements for a bar chart. Adding a model-selectable bar measurement tool gives the Agent reusable geometric evidence while preserving the model's choice of source and how to use uncertain results.

## What Changes

- Add `measure_bars`, accepting either an authorized Attachment or Panel through `source_kind` and `source_id`.
- Return bounded JSON bar geometry, baseline, relative pixel lengths, confidence, status, and warnings in the selected source's pixel coordinate system.
- Extend `RunExecutionState` with a read-only projection of committed measurement outcomes across the current Session's Runs, derived from durable tool facts.
- Keep measurement results in the existing durable tool-execution records; do not add a separate measurement table, session store, frontend endpoint, or image-overlay result channel.
- Preserve uncertain or unsupported observations as candidate evidence. Do not infer exact chart values without calibration or automatically gate later Agent actions on warnings.

## Capabilities

### New Capabilities
- `bar-chart-measurement`: Measure two-dimensional bar geometry from an authorized Attachment or Panel and retain committed results in the reconstructed execution state.

### Modified Capabilities
- `panel-image-observation`: Extend `RunExecutionState` with committed measurement outcomes reconstructed from Session-owned tool facts while retaining its existing attachment and Panel inventory behavior.

## Impact

- Affected code: `src/figura/tools/implementations/`, a focused bar-measurement sensor module under `src/figura/tools/`, `src/figura/agent/execution_state.py`, and tool registration in `src/figura/bootstrap.py`.
- Affected contracts: the new bar-measurement capability and the existing `panel-image-observation` specification. Existing tool-runtime and durable-tool-execution contracts remain the persistence and result-boundary owners.
- No frontend, Gateway API, database schema, or external dependency change is planned.
