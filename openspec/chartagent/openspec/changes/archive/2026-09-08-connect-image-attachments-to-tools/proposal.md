## Why

The agent REPL sends an attached image to the model but removes its `@path`
token from the text, so the model cannot supply the local `image_path` required
by the OCR and geometry tools. The chart-understanding smoke only works around
this gap by manually repeating the path in a special prompt, which means the
normal interactive workflow is not yet connected end to end.

## What Changes

- Include ordered local-image path metadata in the model-visible text whenever
  the agent REPL builds a multimodal turn from `@path` attachments.
- Support quoted attachment references such as `@"/path with spaces/chart.png"`
  while preserving the existing unquoted syntax and image order.
- Give the agent REPL a chart-oriented default system prompt that describes the
  available chart tools as optional capabilities and leaves tool choice and
  response form to the model.
- Update the live chart-understanding smoke to use the same attachment-to-turn
  construction as the REPL, without manually injecting a path or mandating a
  fixed tool sequence.
- Keep plain-text turns unchanged. Do not add a dedicated understanding command,
  forced workflow, automatic ChartSpec output, tool-call guard, or attachment
  sandbox in this change.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `multimodal-input`: Attached image paths remain available to the model for
  optional local-image tool calls, including quoted paths containing spaces.
- `cli-gateway`: The agent REPL uses a chart-aware but non-prescriptive default
  system prompt while retaining free tool choice and natural-language replies.
- `chart-understanding`: Live U0 acceptance runs through the same freely planned
  attachment path used by interactive agent turns rather than a smoke-only
  path-injection prompt.

## Impact

- Modified: `src/chartagent/cli.py`, with a small shared turn-building helper in
  `src/chartagent/multimodal.py` if needed to keep REPL and smoke behavior equal.
- Modified tests: multimodal parsing/forwarding, agent CLI defaults, and live
  chart-understanding smoke coverage.
- Tool schemas and implementations remain unchanged: `extract_text` and
  `measure_bars` continue to accept `image_path`.
- No new runtime dependencies and no breaking programmatic API changes.
