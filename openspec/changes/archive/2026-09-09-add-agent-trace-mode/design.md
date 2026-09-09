## Context

See `proposal.md` for motivation. The current Agent already has the execution
boundaries needed for tracing: `LLMClient.chat()` returns a normalized result,
`Agent.run()` controls model/tool turns, and tool dispatch returns structured
data plus generated-image metadata. The current CLI only renders the final
answer, while provider reasoning is captured and intentionally excluded from
history.

The trace must remain diagnostic. It must not become a second protocol sent to
the model, change native tool-message ordering, or make provider-specific
reasoning fields part of the conversation state.

## Goals / Non-Goals

**Goals:**

- Expose an ordered, provider-neutral trace of one Agent run.
- Offer readable terminal output and newline-delimited JSON events.
- Make tool calls, structured outcomes, warnings, visual evidence, retries, and
  termination easy to inspect.
- Show provider reasoning only behind an explicit option and keep it bounded.
- Keep the default CLI and existing Agent callers unchanged.

**Non-Goals:**

- Persisting traces in a database or building a web dashboard.
- Reconstructing or guaranteeing a model's complete private chain of thought.
- Sending trace events back to the model.
- Printing image payloads, full conversation dumps, API credentials, or raw
  provider responses.
- Changing the free-planning behavior of the Agent.

## Decisions

### 1. Use a callback-based provider-neutral trace event

Introduce a small trace event value object with an event kind, run/turn
position, and JSON-serializable payload. Agent and client boundaries emit events
through an optional callback or sink; the core path does nothing when no sink is
configured.

Representative event kinds are:

```text
model_started
model_completed
reasoning
tool_call
tool_result
visual_observation
final_answer
budget_exhausted
```

The event contract deliberately describes observable execution, not provider
raw response objects. A sink can therefore render text, JSONL, or a future UI
without coupling the Agent to a terminal formatter.

Alternative considered: have the CLI inspect `Agent.messages` after each turn.
Rejected because message history intentionally excludes reasoning and does not
represent tool timing, failures, or image metadata as a stable diagnostic API.

### 2. Emit events at execution ownership boundaries

`LLMClient` reports model-call completion and normalized reasoning availability;
`Agent` reports tool-call intent, tool completion, visual evidence, final answer,
and budget termination. This preserves ownership:

```text
LLMClient -> model request/response facts
Agent     -> planning and lifecycle facts
CLI       -> rendering only
```

Tool-result payloads are summarized before emission. The underlying tool result
and model messages remain unchanged.

### 3. Separate trace mode from reasoning display

`--trace` enables execution events. A separate `--trace-reasoning` option
controls whether provider-returned reasoning is rendered. This keeps useful
tool diagnostics available without automatically exposing potentially sensitive
or very long reasoning content.

Both options apply to the Agent REPL; the existing Conversation REPL remains
unchanged. Reasoning is never appended to model history regardless of display
settings.

### 4. Render human text and JSONL through independent sinks

The human renderer writes diagnostics to stderr so the final answer on stdout
remains usable for piping or copying. It groups events by turn and labels
reasoning as provider-returned diagnostic content.

The structured renderer writes one JSON object per line. It includes event kind,
turn, tool identity, status, captions, byte counts, and bounded text fields,
but never image bytes or credentials.

### 5. Bound and sanitize at the trace boundary

Use centralized trace limits for reasoning, tool arguments, tool results, and
captions. Apply redaction before a sink receives an event, not inside only the
terminal renderer, so JSON output receives the same protection. Truncation
must carry an explicit marker. Image events carry media type, caption, and byte
count only.

## Risks / Trade-offs

- **Provider reasoning may contain sensitive or confusing content** -> Require
  an explicit display option, label it as provider-returned, bound it, and keep
  it out of history.
- **Trace formatting could accidentally change Agent behavior** -> Keep the
  event sink optional and side-effect-free; emit after the same execution
  boundaries without modifying messages.
- **Tool arguments/results may contain secrets or huge data** -> Centralize
  redaction and truncation before all sinks, including JSONL.
- **Streaming output is not immediately visible** -> First version emits
  normalized model events after each provider call; token-level live rendering
  remains a later enhancement requiring a streaming callback contract.
- **Different providers expose different reasoning fields** -> Treat reasoning
  as optional normalized data and emit an unavailable status when absent.

## Migration Plan

1. Add trace event types, bounded payload summarization, and optional sinks.
2. Instrument normalized model responses and Agent/tool lifecycle boundaries.
3. Add CLI argument handling and text/JSONL renderers while preserving default
   output.
4. Add offline tests for event order, redaction, truncation, reasoning opt-in,
   visual metadata, and legacy quiet behavior.
5. Run the full suite in the Conda `agent` environment and perform a bounded
   live trace smoke against the configured provider.

Rollback is simply to omit trace options or remove the sink from the CLI; the
core model/tool message path remains unchanged.
