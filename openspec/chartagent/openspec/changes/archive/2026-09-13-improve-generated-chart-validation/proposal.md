## Why

Figura currently verifies that a ChartSpec can be parsed and that Matplotlib
can produce a PNG, but it does not verify that the rendered chart preserves
the intended data or remains readable. The independent `validate_spec` tool
and `render_chart` also have different semantic rules, while missing grouped
bar values can be silently rendered as zero. Generated charts are user-facing
artifacts, so these gaps should be closed before treating a successful render
as a trustworthy result.

## What Changes

- Centralize generation-time ChartSpec validation and use the same rules from
  `assemble_spec`, `validate_spec`, and `render_chart`.
- **BREAKING**: stop interpreting an absent grouped-bar value as an actual
  zero; reject or explicitly diagnose ambiguous missing categorical data.
- Validate chart-type semantics consistently, including duplicate categorical
  points, pie totals, finite values, and axis range constraints.
- Apply declared numeric axis ranges during rendering and report invalid or
  unusable ranges before an artifact is published.
- Add a deterministic post-render audit for data-to-artist coverage and
  layout bounds, including titles, labels, tick labels, annotations, and
  legends.
- Fully verify the encoded PNG before returning it, in addition to existing
  size and dimension limits.
- Return bounded structured validation diagnostics with passed, warning, or
  failed status and per-check results alongside successful chart metadata.
- Keep layout warnings recoverable and bounded; semantic or artifact failures
  must not publish a generated chart.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `chart-generation`: strengthen ChartSpec semantic validation, generated
  chart fidelity and layout checks, PNG artifact verification, and validation
  diagnostics returned by the rendering tool.

## Impact

- Affected Python modules include the ChartSpec validation helpers, chart
  assembly/validation tools, and the Matplotlib generation tool.
- The `render_chart` tool result gains a bounded validation object; existing
  image bytes, artifact kind, size limits, and Gateway ownership rules remain
  unchanged.
- Tests must cover validator parity, missing data, axis ranges, artist
  fidelity, layout overflow, malformed or blank output, and warning behavior.
- No new runtime dependency, database migration, frontend renderer, or visual
  language-model review is introduced in this phase.
