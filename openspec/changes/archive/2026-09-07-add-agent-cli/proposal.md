# Add Agent CLI Shell

## Why

The ReAct `Agent` is currently a library API only (verified via mock tests); the
only interactive command-line entry is `Conversation`-based (`cli.py` →
`run_repl`), which never registers tools and never lets the model call them. The
agent loop's tool-calling capability is thus invisible from the terminal. This
change gives the `Agent` a thin interactive shell so a user can drive a
tool-capable ReAct loop from `python -m chartagent`.

## What Changes

- An agent-driven REPL path on the CLI: register the built-in read-only tools,
  build an `Agent`, and loop read-a-line → `agent.run(line)` → print reply,
  exiting on empty line / Ctrl-D (same interaction shape as the existing chat
  REPL).
- Preserve the existing `Conversation`-based chat REPL as the default, and
  expose the tool-capable agent shell behind an explicit flag (e.g. `--agent`)
  so the two interaction modes coexist without surprise.
- Reuse `register_builtins` / `ToolRegistry` / `Agent` as-is; no loop changes.

## Non-Goals

- No change to `Agent` semantics or loop internals (already covered by
  `agent-loop`).
- No new tools beyond the already-registered built-ins.
- No persistence / streaming UI / colored rendering.
- No multi-session or server; still a single in-memory session per launch.