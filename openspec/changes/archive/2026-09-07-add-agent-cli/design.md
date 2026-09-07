# Design

## Context

`cli.py` already hosts `run_repl(model, system)` built on `Conversation`, and
`cli(argv)` parses `--model`. We add a parallel agent path without disturbing
the default. `Agent`, `ToolRegistry`, and `register_builtins` are already
integrated and archived.

## Decision 1: Agent shell behind an explicit `--agent` flag

`cli()` gains an `--agent` flag; when present it calls a new `run_agent_repl`,
otherwise it falls through to the existing `run_repl`. This keeps `Conversation`
as the default (no surprise on upgrade) and makes the tool-capable mode opt-in.

## Decision 2: `run_agent_repl` reuses the same shell shape

Same read-a-line → reply → exit contract as `run_repl`:

```python
def run_agent_repl(*, model=None, system="You are a helpful assistant.") -> int:
    load_environment()
    client = LLMClient()
    registry = ToolRegistry()
    register_builtins(registry)
    agent = Agent(client, registry, system=system, model=model)
    # loop: read line → agent.run(line) → print; blank/Ctrl-D -> exit
```

`model` is forwarded through `Agent(**chat_kwargs)` to `client.chat`.

## Decision 3: Both entry points keep a single in-memory session

`run_repl` and `run_agent_repl` are independent functions, each owning one
in-memory session for the process. No cross-session state.

## Decision 4: `scripts/chat_cli.py` and `__main__.py` delegate unchanged

The thin delegated entry points already call `cli.cli()`; they need no change —
the `--agent` flag flows through `cli(argv)` as-is.

## Risks / unknowns

- Tool-capable agent turns can take multiple steps; replies may be slower than
  plain chat. Acceptable for an interactive shell; no streaming UI this change.
- `Agent` currently starts a session per `run` from its own history — the REPL
  reuses one `Agent` instance so multi-line history accumulates across the
  session, matching the conversation REPL's behavior.