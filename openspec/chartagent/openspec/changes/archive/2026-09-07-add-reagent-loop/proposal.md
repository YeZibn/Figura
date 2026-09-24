# Add ReAct Agent Loop

## Why

Conversation offers multi-turn dialogue, tool-system offers dispatch, and the
built-in read-only tools give a safe action surface — but nothing yet drives the
tool-calling loop. An agent loop is the piece that lets a model take actions
(Thought → Action → Observation → Final answer) until a task is finished. This
change builds that minimal ReAct loop as a pure-function-calling loop: it reuses
`LLMClient.chat` for the thinking/reasoning, `ToolRegistry` + `dispatch` for
observations, and registers existing built-in tools.

## What Changes

- New `Agent` class that owns its message history in memory and runs one user
  turn to completion.
- A ReAct-style loop: while the model returns `tool_calls`, execute them
  serially, append `tool` observations, and repeat; stop when a turn returns no
  tool calls (final answer) or the step budget is exhausted.
- New assistant-side history construction that keeps `tool_calls` (the
  conversation loop intentionally strips them; the agent loop must keep them so
  the model can see its own actions and observations).
- Reuse of `registry_tools` from existing built-in tools; structured errors from
  `dispatch` flow back into the loop as observations.

## Non-Goals

- No concurrent tool execution (tool calls run serially in this change).
- No memory compression / summarization / persistence.
- No separate Critic / verification stage (revisited when chart tools land).
- No explicit ReAct-syntax text parsing — the loop relies on native function
  calling and the model's inherent reasoning.
- No built-in system prompt template — the caller supplies whatever `system`
  they want.