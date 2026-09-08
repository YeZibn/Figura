# Tasks: add-chart-understanding

## 0. Environment

- [x] 0.1 Install the project editable into the conda env `agent`: `conda run -n agent pip install -e .`; verify `conda run -n agent python -c "import chartagent"` succeeds.

## 1. Dependencies and scaffolding

- [x] 1.1 Declare runtime deps `rapidocr` (>=3.8, already in env), `numpy`, `pillow` and dev dep `matplotlib` in `pyproject.toml`; install matplotlib into `agent` (`conda run -n agent pip install matplotlib`); verify `from rapidocr import RapidOCR` and Agg-backend matplotlib imports.
- [x] 1.2 Create `src/chartagent/tools/chart/` package with `__init__.py` and `register.py` exposing `register_chart_tools(registry)` (initially registering nothing, filled in later tasks).

## 2. Synthetic chart fixtures

- [x] 2.1 Add `tests/chart_fixtures.py`: helpers drawing annotated bar charts with matplotlib (Agg) from explicit values/labels; return `(png_bytes, ground_truth)`.
- [x] 2.2 Write fixture smoke test: a generated chart file exists and is a valid PNG.

## 3. Sensors

- [x] 3.1 Implement `chart/ocr.py`: `extract_text(image_path)` tool — lazy rapidocr singleton, returns `[{text, bbox, confidence}]`, structured `{"error"}` on missing file.
- [x] 3.2 Implement `chart/geometry.py`: `measure_bars(image_path)` tool — color-column scanning per design D3; returns `{bars: [{bbox, h_px, ratio}], baseline_y}`; empty bars list for non-chart images.
- [x] 3.3 Tests: OCR snippets contain all ground-truth annotations; bar count exact and ratios within 10% of true value ratios; missing-file error shape; blank-image empty result.

## 4. Spec tools

- [x] 4.1 Implement `chart/spec_tools.py`: `assemble_spec` tool per design D4 (enum check, cartesian axes requirement, per-type point-shape validation, `ChartSpec(...).to_dict()` output, structured errors).
- [x] 4.2 Implement `validate_spec` tool per design D5 (`from_dict` + `validate()`, `{"ok", "issues"}` output, no exceptions escape).
- [x] 4.3 Tests: valid bar/line specs assemble and round-trip; missing axes for cartesian, bad type, malformed points produce structured errors; validate passes clean specs and locates issues on empty dataset / mixed shapes.

## 5. Wiring

- [x] 5.1 `register_chart_tools` registers all four tools; agent REPL in `cli.py` calls it after `register_builtins`.
- [x] 5.2 Test: agent REPL registry exposes the four chart tools alongside built-ins.

## 6. End-to-end and acceptance

- [x] 6.1 Offline E2E test: fake client scripted through the full trajectory (sensors → cross-check → assemble → validate) against a synthetic chart; final spec equals ground truth.
- [x] 6.2 `scripts/smoke_chart_understanding.py`: real-endpoint U0 acceptance on 2–3 synthetic annotated bar charts; run manually and record results.
- [x] 6.3 Full regression suite green.
