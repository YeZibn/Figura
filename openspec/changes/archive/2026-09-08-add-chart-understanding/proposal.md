# Proposal: add-chart-understanding

## Why

ChartAgent's understanding side has never consumed real images: the ChartSpec
IR exists but nothing produces one. This change delivers U0 — reading a clean
bar chart with printed value annotations — as a set of agent tools, so the
VLM-powered agent (which can now see images via `add-image-input`) performs
chart understanding through a real ReAct loop: sense, reason, assemble,
validate. It also stress-tests the ChartSpec schema against a real
restoration, closing the loop the IR was designed for.

## What Changes

- New tool group `chart` under `src/chartagent/tools/chart/`, registered via
  `register_chart_tools(registry)` and wired into the `--agent` REPL:
  - `extract_text(image_path)` — deterministic OCR over the whole image
    (rapidocr 3.x, preinstalled in the conda env `agent`): every text snippet
    with bounding box and confidence. No bbox input — whole-image sensor.
  - `measure_bars(image_path)` — deterministic CV for clean bar charts
    (numpy + PIL, no OpenCV): detect bars via color-column scanning, return
    each bar's bbox, pixel height, and height ratio normalized to the shortest
    bar. Geometric evidence for cross-validation.
  - `assemble_spec(...)` — code-side ChartSpec construction: takes
    chart_type, title, axis labels, points, source; builds a valid
    `ChartSpec` and returns its dict. The model never hand-writes IR JSON.
  - `validate_spec(spec)` — the Critic as an independent tool: `from_dict` +
    `validate()`, returns `{ok, issues}`. The agent chooses when to run it.
- Division of labor (hybrid architecture): the VLM sees the image and does
  semantic association (which number labels which bar, what the categories
  are); tools provide only deterministic measurements. Cross-validation is
  agent-side reasoning over two evidence channels (annotation values vs bar
  height ratios), with `validate_spec` as the schema gate.
- Dependencies (conda env `agent` is the single runtime): `rapidocr` 3.x,
  `numpy`, `pillow` already present in the env — declared in pyproject to
  match; dev adds `matplotlib` (the only genuinely missing package) for
  synthetic ground-truth charts in tests.
- Explicitly out of scope: axis pixel→value calibration (U0 annotations make
  it unnecessary), round-trip render check (needs the generation side),
  non-bar chart types, history slimming.

## Capabilities

### New Capabilities

- `chart-understanding`: agent tools that sense a chart image (OCR text,
  bar geometry), assemble a ChartSpec in code, and validate it as an
  independent critic step; plus the U0 end-to-end behavior of restoring
  annotated bar charts to ChartSpec through the ReAct loop.

### Modified Capabilities

- (none — the chart tool group and its agent-REPL wiring are requirements of
  the new `chart-understanding` capability; existing capabilities' behavior is
  unchanged)

## Impact

- New: `src/chartagent/tools/chart/` (ocr.py, geometry.py, spec_tools.py,
  register.py), `tests/test_chart_tools.py`, synthetic-chart helpers in
  `tests/`.
- Modified: `src/chartagent/cli.py` (`register_chart_tools` call),
  `pyproject.toml` (dependencies).
- Depends on: `add-image-input` (the agent must be able to see the image).
- Benchmark: U0 acceptance = restore a synthetic matplotlib bar chart with
  known values to a ChartSpec whose dataset matches ground truth, via the
  real endpoint.
