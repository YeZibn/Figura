## 1. Rendering Foundation

- [x] 1.1 Promote Matplotlib to the `agent` runtime dependency and configure a headless backend with a bounded default and maximum output size.
- [x] 1.2 Add a chart-generation renderer that converts validated ChartSpec data into bounded PNG bytes and metadata without exposing local paths.
- [x] 1.3 Implement single-series and grouped bar rendering while preserving category and series identities.
- [x] 1.4 Implement line, pie, and scatter rendering with their ChartSpec-specific validation rules, labels, legends, and series grouping.
- [x] 1.5 Add renderer-level structured errors for invalid points, missing axes, invalid pie totals, unsupported values, and output-limit violations.

## 2. Agent Tool Boundary

- [x] 2.1 Define the `render_chart` tool schema and register it with the existing chart tools without changing image-understanding tool inputs.
- [x] 2.2 Return structured chart metadata and a validated GeneratedImage through the existing ToolResult boundary, converting renderer failures into safe tool errors.
- [x] 2.3 Update Agent runtime guidance so chart generation is available as an optional action after assembling or validating a ChartSpec, without imposing a fixed sequence.
- [x] 2.4 Add Python tests for all four chart types, grouped series, invalid specs, metadata bounds, deterministic output dimensions, and tool error recovery.

## 3. Gateway Artifact and History

- [x] 3.1 Extend Gateway protocol types with generated-chart metadata, artifact references, and an event representation distinct from temporary visual observations.
- [x] 3.2 Add an additive persistence path for `generated_chart` artifacts linked to a session and run, retaining existing observation records and migrations.
- [x] 3.3 Persist generated chart bytes through the existing run artifact boundary and emit bounded metadata in the correct execution order.
- [x] 3.4 Add authorized session/run-scoped generated-artifact reads for preview and download, including retention, ownership, and unavailable responses.
- [x] 3.5 Extend session deletion and artifact cleanup tests to remove generated charts without affecting artifacts owned by another session.
- [x] 3.6 Add Gateway tests for artifact authorization, reload hydration, bounded metadata, rendering failures, retention expiry, and event-history compatibility.

## 4. React Workspace

- [x] 4.1 Extend frontend protocol types and Gateway/mock clients with generated-chart artifact references and retrieval behavior.
- [x] 4.2 Add a generated-chart execution timeline item with chart type, title/caption, dimensions, size, and explicit generation status.
- [x] 4.3 Add authorized preview and accessible download behavior while keeping generated charts distinct from source attachments and model observations.
- [x] 4.4 Restore generated-chart metadata after session reload and render bounded unavailable or failed states without broken image URLs.
- [x] 4.5 Add deterministic mock data and browser smoke assertions covering successful generation, preview, download affordance, and unavailable artifacts.

## 5. Verification and Documentation

- [x] 5.1 Run the complete Python test suite with `conda run -n agent python -m pytest` and fix renderer or Gateway regressions.
- [x] 5.2 Run the frontend TypeScript build and documented smoke checks for Gateway and mock modes.
- [x] 5.3 Add usage notes for generating a chart from an existing ChartSpec or an understood image, including the distinction between generated artifacts and temporary observations.
- [x] 5.4 Run strict OpenSpec validation for the change and main specs, then run `git diff --check`.
