## Context

See `proposal.md` for the motivation. The current renderer creates one
Matplotlib figure for each `render_chart` call and relies on the default
DejaVu Sans family. The Gateway can render charts concurrently, so global
Matplotlib configuration is not a safe ownership boundary.

## Goals / Non-Goals

**Goals:**

- Resolve a usable CJK font consistently across macOS, Linux, and Windows.
- Apply the resolved font to every generated text object in all four chart
  renderers.
- Expose bounded font metadata and fallback warnings without changing the
  artifact protocol.
- Keep rendering headless, deterministic in layout, and safe for concurrent
  Gateway runs.

**Non-Goals:**

- Bundling a font file into the repository in this change.
- Changing ChartSpec styling, chart layout, colors, or dimensions.
- Adding a frontend font or browser-rendering path.

## Decisions

### D1: Use an explicit font resolution order

The resolver first checks `CHARTAGENT_FONT_PATH` when it points to a readable
font file, then searches a platform-neutral ordered set of CJK families:
`PingFang SC`, `Hiragino Sans GB`, `Microsoft YaHei`, `SimHei`, `Noto Sans CJK
SC`, and `WenQuanYi`. The result carries a source such as `configured` or
`system`; the selected path/name is bounded before entering metadata.

An environment override is preferred over bundling because the current
desktop workflow already runs inside a user-managed Conda environment and the
repository should not ship a font without an explicit licensing decision. A
future packaged distribution can add a licensed bundled font without changing
the renderer contract.

### D2: Apply `FontProperties` per text object

The renderer passes one resolved `FontProperties` object to titles, axis
labels, tick labels, legends, bar annotations, pie labels, and pie percentage
texts. It does not mutate global `rcParams` or rely on process-wide font state,
which avoids cross-talk between concurrent render calls.

The helper should also support a no-font result. In that case the normal
Matplotlib fallback remains usable for non-CJK content, while the tool result
adds a bounded warning and metadata status such as `fallback`.

### D3: Keep diagnostics in tool metadata and warnings

Successful output keeps the existing `GeneratedImage` and artifact shape. Its
structured data gains bounded font status/name/source fields, and the
`ToolResult.warnings` collection records invalid overrides or unavailable CJK
fonts. No local font path is exposed through Gateway events; if paths must be
used internally, metadata should contain only a family name or source label.

### D4: Test semantics, not PNG bytes

Tests will render Chinese text for bar, line, pie, and scatter specs, assert the
font status and bounded warning behavior, and preserve existing dimensions and
metadata assertions. A fallback test will force resolution failure. Pixel
snapshot comparison is intentionally avoided because fonts and antialiasing
vary by operating system.

## Risks / Trade-offs

- [System font names and collection formats vary by OS] -> Use Matplotlib font
  discovery, multiple family candidates, and an explicit override.
- [A font may exist but lack a particular CJK glyph] -> Keep fallback status
  observable and document the override for deployments with strict coverage.
- [Per-object font assignment adds code to each renderer] -> Centralize the
  font resolver and text-application helpers while keeping chart semantics
  unchanged.
- [Font caches can be stale] -> Resolve through Matplotlib's font manager at
  runtime and avoid modifying global cache files from the tool.

## Migration Plan

1. Add the resolver and per-object application helpers to the Python renderer.
2. Add semantic rendering and fallback tests under `tests/test_chart_generation.py`.
3. Run the full Python suite and frontend smoke/build checks; no database or
   Gateway migration is required.
4. If resolution causes a regression, disable the override path and retain the
   existing renderer while preserving the structured warning contract.
