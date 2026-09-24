## 1. Trace Contract And Sanitization

- [x] 1.1 Add provider-neutral trace event types with event kind, run/turn
  metadata, JSON-serializable payloads, and an optional trace sink.
- [x] 1.2 Add centralized trace limits, truncation markers, credential-like
  field redaction, and generated-image metadata summarization without emitting
  image bytes.
- [x] 1.3 Add unit tests for event serialization, ordering fields, truncation,
  redaction, reasoning-unavailable status, and image metadata safety.

## 2. Agent And Client Instrumentation

- [x] 2.1 Emit model-start/model-completed events from the LLM integration
  boundary without changing normalized results or model messages.
- [x] 2.2 Emit Agent tool-call, tool-result, visual-observation, final-answer,
  and budget-exhausted events in execution order.
- [x] 2.3 Emit provider-returned reasoning only through the trace path when the
  explicit reasoning-display option is enabled, while keeping it out of
  conversation history.
- [x] 2.4 Add offline tests proving traced and untraced Agent runs have the
  same model messages, tool behavior, returned answer, and step-budget result.
- [x] 2.5 Add offline tests for multi-tool ordering, structured tool errors,
  generated overlay metadata, and reasoning isolation.

## 3. CLI Trace Modes

- [x] 3.1 Add Agent CLI options for `--trace`, `--trace-reasoning`, and a
  structured JSONL trace format while preserving the existing conversation and
  quiet Agent defaults.
- [x] 3.2 Implement a human-readable stderr renderer that groups events by
  turn and leaves the final answer on the normal output stream.
- [x] 3.3 Implement JSONL rendering with one sanitized event per line and no
  raw credentials, image bytes, or unbounded text.
- [x] 3.4 Add CLI tests covering default behavior, trace output, reasoning
  opt-in/omission, JSONL validity, and malformed option combinations.

## 4. Verification And Provider Smoke

- [x] 4.1 Run focused Agent, client, tool-observation, and CLI tests through
  `conda run -n agent python -m pytest ...` and resolve regressions.
- [x] 4.2 Add an offline recorded trajectory fixture covering OCR/bar tools,
  visual evidence, a retry, and a final answer in both text and JSONL traces.
- [x] 4.3 Add a bounded live trace smoke using the configured provider that
  records tool calls and visual-observation metadata without exposing secrets.
- [x] 4.4 Run the complete suite with `conda run -n agent python -m pytest -q`
  and validate the change with `openspec validate add-agent-trace-mode --strict`.
