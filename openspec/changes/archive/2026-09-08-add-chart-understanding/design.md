# Design: add-chart-understanding

## Context

U0 scope: clean matplotlib-style bar charts with printed value annotations.
The agent (multimodal, via `add-image-input`) sees the image and does semantic
association; four tools do measurement, assembly, and validation. Division of
labor is fixed by project constraints: VLM plans and associates, CV/OCR
measure, Critic is a separate step.

## Decisions

### D1: Sensor design — whole-image, no region arguments

Both sensors take only `image_path` and dump all deterministic evidence.
Rationale: VLM pixel grounding is unreliable; asking the model for bboxes would
inject its weakest capability into the pipeline. Association (which number
labels which bar) is done by the agent, which is exactly what it is good at.

### D2: OCR via rapidocr-onnxruntime, lazily initialized

- Module-level singleton engine created on first `extract_text` call; import
  happens inside the function so `chartagent` stays importable without the
  dependency installed.
- Output per snippet: `{"text", "bbox": [x, y, w, h], "confidence"}`.
- Confidence from the engine's rec score; U0 uses it only as provenance.

### D3: Bar detection by dominant-color column scanning (numpy + PIL, no OpenCV)

For clean synthetic bar charts:

1. Load as RGB array; classify pixels: background = near-white, ink = near-gray
   /black (axes, text), else "color".
2. The dominant non-ink color is the bar color (single-series U0).
3. Column scan: per column, the topmost contiguous run of bar color gives its
   top; columns with bars grouped into bars by adjacency.
4. Baseline = median bottom of detected bars; `h_px = baseline - top`.
5. `ratio = h_px / min(h_px)` — the tool pre-computes ratios so the agent never
   does arithmetic on raw pixels (LLM arithmetic is a known weakness; the
   cross-check is then a ratio-vs-ratio comparison the agent can reason about).

Return: `{"bars": [{"bbox", "h_px", "ratio"}], "baseline_y"}`.
Empty list (not error) when nothing matches — "no bars" is a valid observation
the agent re-plans from.

### D4: `assemble_spec` builds axes from labels; shape enforced in code

Args: `chart_type`, `title`, `x_label`, `y_label`, `points` (array of
`{category?, value?, x?, y?, confidence?}`), `source`. Code-side checks before
construction: type in enum; cartesian types require `x_label`/`y_label`;
bar/pie points require `category`+`value`, line/scatter require `x`+`y`.
Failure → `{"error": ...}`. Success → `ChartSpec(...).to_dict()` with
`metadata = {"source": source, ...}`. This is the "code assembly is more
stable" decision: structure is guaranteed, values remain the agent's
responsibility.

### D5: `validate_spec` is the Critic, not a pipeline stage

`from_dict` (unknown fields dropped, shapes coerced) then `validate()`;
returns `{"ok": len(issues) == 0, "issues": [issue dicts]}`. The agent decides
when to call it (typically once after assembly, again after fixes). It is never
auto-invoked inside `assemble_spec` — keeping the critic separate is an
explicit project constraint.

### D6: Registration and wiring

`src/chartagent/tools/chart/register.py` exposes `register_chart_tools(reg)`
mirroring `register_builtins`. `cli.py` calls both at agent-REPL startup.
Files: `ocr.py`, `geometry.py`, `spec_tools.py`, `register.py`, `__init__.py`.

### D7: Tests use synthetic charts with known ground truth

- Dev dependency `matplotlib` (Agg backend, no display). Fixture helpers draw
  bar charts from explicit values + labels; ground truth is the input.
- Unit tests: OCR snippets ⊇ annotations; bar count exact, ratios within 10%;
  assemble/validate pure-logic matrix; error paths.
- E2E (offline): fake client scripted to run the full tool-call trajectory on
  a synthetic image, asserting final spec equals ground truth — proves the
  loop mechanics, not model quality.
- Live smoke (manual, not CI): `scripts/smoke_chart_understanding.py` runs the
  real endpoint against 2–3 synthetic charts; this is the U0 acceptance gate.

## Dependencies

- Environment: conda env `agent` is the single runtime; install the project
  editable there (`conda run -n agent pip install -e .`) as task 0.
- runtime: `rapidocr` (3.x, already in env), `numpy`, `pillow` (declare in
  pyproject to match the env; no new downloads needed)
- dev: `matplotlib` (only genuinely missing package; install into `agent`)
- IR (`chartspec`) unchanged; client/agent/tool-system unchanged.

## Risks

- rapidocr 3.x model files: preinstalled package may fetch models on first
  run; verify offline model availability during task 3.1 before relying on it.
- Color scanning is tuned to clean charts by design; noisy real-world charts
  are explicitly U1+ and will need the calibration pipeline this change
  defers.
- Endpoint image size limits: U0 fixtures are small; documented, not handled.
