## Why

The Agent currently exposes only its final answer in the CLI, even though the
runtime already receives provider reasoning, tool calls, structured tool
results, and generated visual observations. This makes chart-understanding
failures and unexpected tool plans difficult to inspect, so an explicit,
opt-in trace mode is needed for development and evaluation without changing
the default user experience.

## What Changes

- Add an opt-in Agent CLI trace mode that renders model turns, tool calls,
  tool results, visual-observation summaries, retries, and the final answer.
- Add a separate opt-in reasoning display switch for provider-returned
  reasoning content when the configured model exposes it; reasoning remains
  excluded from conversation history.
- Introduce a provider-neutral trace-event contract so the Agent and client
  can emit observability events without coupling core execution to terminal
  formatting.
- Support human-readable terminal traces and a structured JSON trace format
  suitable for offline trajectory inspection.
- Keep trace output bounded and sanitized: never print API credentials, image
  base64 payloads, or unbounded tool-result content.
- Preserve existing CLI behavior and output when trace mode is not enabled.

## Capabilities

### New Capabilities

- `agent-observability`: Provider-neutral trace events and bounded, sanitized
  inspection of Agent execution.

### Modified Capabilities

- `agent-loop`: The Agent can publish execution events for model turns, tool
  calls, tool results, generated visual observations, and final outcomes.
- `cli-gateway`: The Agent REPL accepts explicit trace options while retaining
  the existing quiet default mode.

## Impact

- Affects the Agent loop, LLM client integration points, CLI argument handling,
  and tests for tool/reasoning/message behavior.
- Adds no runtime dependency and does not alter the messages sent to the model
  or the reasoning-isolation contract.
- Adds local diagnostic output only; trace content is not persisted unless the
  user selects structured output and redirects or records it externally.
- Provider reasoning is best-effort and model-dependent; the trace must label
  it as provider-returned reasoning rather than assuming it is always present
  or equivalent across models.
