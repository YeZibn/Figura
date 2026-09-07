# Design

## Context

We have, already integrated and archived:
- `llm-client`: `LLMClient.chat(messages, model=..., tools=..., ...)` returns a
  `NormalizedResult` with `content`, `reasoning`, `tool_calls[]`
  (`id`/`name`/`arguments`), `finish_reason`, `usage`, `raw`. It echoes reasoning
  into `result.reasoning` but its `append_to_history` keeps assistant history
  `content`-only.
- `conversation-loop`: `Conversation` drives pure multi-turn dialogue; it is a
  **non-tool** loop and strips tool calls from history.
- `tool-system`: `Tool`, `ToolRegistry.register/get/list`, and `dispatch`
  (name + JSON args → JSON string; failures become `{"error": ...}`).
- `basic-tools`: `register_builtins(registry)` + `TOOL_NAMES` and
  `registry_tools` for the read-only file/data tools.

## Decision 1: The agent loop is a native function-calling loop, not text ReAct

The model is given the registered tools as native `tools`; its `tool_calls`
are the Actions, `dispatch` results are the Observations, and a turn with no
tool calls is the Final Answer. We do **not** parse a textual
`Thought:/Action:/Observation:` protocol — reasoning is carried by the model's
own `reasoning` (and free text), not parsed.

## Decision 2: Agent owns history differently from Conversation

Conversation's `append_to_history` intentionally drops `tool_calls`. The agent
loop needs its own assistant-entry constructor that keeps `content` + `tool_calls`
and separately appends `tool` messages per call. Reasoning is still never echoed
into history (deep-thinking providers 400 otherwise). This is the core new
behavior vs `conversation-loop`.

History shape per step:

```json
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {
    "role": "assistant",
    "content": "...",
    "tool_calls": [{"id": "…", "type": "function",
                    "function": {"name": "…", "arguments": "…"}}]
  },
  {"role": "tool", "tool_call_id": "…", "content": "…"},
  ...
]
```

## Decision 3: Tool calls execute serially in this change

If the model returns several `tool_calls` in one turn, they run one after
another, each appending its own `tool` observation before the next call. No
concurrency in this change.

## Decision 4: No built-in system prompt template

ReAct emerges from native tool calling + the model's reasoning. The caller
supplies `system`. The agent only concatenates the supplied system and the user
input.

## Decision 5: Configuration surface

`Agent(client, registry, *, system=None, max_steps=…)` keeps the loop toggles
(`max_steps`, `system`) explicit rather than hidden; `chat`-level knobs (model,
thinking, temperature) remain forwardable by the caller.

## Risks / unknowns

- Some providers need `tool_calls` echoed back verbatim across turns; because we
  reload them into the assistant history entry exactly as returned, this holds.
- Token growth: full history is retained in memory (non-goal to compress here).