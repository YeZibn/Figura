# Evidence-fusion implementation baseline

Captured before implementing `model-assisted-chart-evidence-fusion` on 2026-09-16.
The direct sensor run used `conda run --no-capture-output -n agent python` and
the existing synthetic fixtures from `tests/chart_fixtures.py`. The existing
frontend/Gateway trace was read from `/tmp/figura-run-latest.json`.

## Direct sensor baseline

| Case | Sensor | Key result | Confidence | Warnings | Overlay |
| --- | --- | --- | --- | --- | --- |
| Synthetic bar | `measure_bars` | 3 bars; vertical; baseline residual 2 px against visible axis; cross-check consistent | overall 0.96 | none | 1, 18,134 bytes |
| Synthetic line | `extract_line_series` | 2 series; 2 traces; upright frame; X calibration present, Y calibration absent | overall 0.7325 | Y calibration unavailable; trace crossing/fragmentation | 1, 30,458 bytes |
| Synthetic pie | `extract_pie_slices` | 4 sectors; totals 360° / ratio 1.0; totals consistent | overall 0.9765 | none | 1, 20,418 bytes |
| Synthetic scatter | `extract_scatter_points` | 2 series; 10 points; upright frame; no numeric calibration | overall 0.7123 | series labels and X/Y calibration unresolved | 1, 21,757 bytes |
| Real shareholder/price line | `extract_line_series` | 2 series; 41 points per series; upright frame; Y calibration confidence 0.9952 | overall 0.7325 | X calibration unavailable | 1, 363,741 bytes |

## Existing Agent trace baseline

Run `run_33e73254575c4e619f31a91c4b12a46f` used provider/model
`qwen/qwen3.7-flash` against `股东人数与前复权股价折线图.png`.

- 22 events were recorded.
- The model first called `load_image`, then called `inspect_chart_layout`
  without a `layout_hint`; the Agent supplied the deterministic fallback.
- The trace used 15 registered tools and did not expose a visual overlay from
  `inspect_chart_layout` itself.
- Layout fallback: `bbox_px [367, 242, 2734, 1885]`, confidence `0.14`,
  `accepted_for_measurement=false`.
- The subsequent line result found an upright frame
  `[219, 273, 3048, 1858]`, two series, and 41 points per series.
- The trace reported a false legend association (`May-22`) for one series,
  no label for the other series, and an OCR error (`6T-Inr` for `Jul-19`).
- The trace's final overall confidence was `0.7325`; geometry was strong,
  while X-axis semantic calibration remained unavailable.

This baseline intentionally records current behavior rather than declaring
sensor output to be ground truth. It will be compared with the post-change
model-led and targeted-evidence paths.

## Post-change frontend/Gateway chain

On 2026-09-16, the supplied `股东人数与前复权股价折线图.png` was uploaded
through the Gateway attachment endpoint and submitted through the live-run
endpoint on an isolated `npm run dev:gateway` instance. The run used
`qwen/qwen3.8-max` and `run_19e5876d224c41fc802717c8d677bfb5`.

- The frontend-facing path successfully registered the PNG attachment and
  created the run with an opaque attachment ID.
- The model selected `load_image`, then targeted `extract_text` and
  `extract_line_series`; no `inspect_chart_layout` call was inserted by the
  Agent.
- Both OCR and line geometry returned success observations. The line sensor
  preserved the independent frame `[219, 273, 3048, 1858]`, two series, and
  41 points per series, with a source-sized overlay.
- The run reached 15 Gateway events and then remained at `model_started`
  for turn 3 while the Provider connection continued waiting. The isolated
  services were stopped after no further event for several minutes, so this
  run did not produce a final answer. This is recorded as a Provider/runtime
  latency limitation, not as a successful structured restoration.
