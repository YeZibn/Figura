"""Interact access programmatically via an in-memory conversation.

Simple read-a-line → reply → repeat loop; history stays in memory. Two
interaction modes: the default ``Conversation`` chat REPL, and a tool-capable
``Agent`` ReAct REPL selected via ``--agent``.
"""

from __future__ import annotations

import sys

from .agent import Agent
from .conversation import Conversation
from .client import LLMClient, load_environment
from .tools import ToolRegistry
from .tools.builtin import register_builtins


def run_repl(
    *,
    model: str | None = None,
    system: str = "You are a helpful assistant.",
) -> int:
    """Run an interactive chat loop against the configured endpoint.

    Returns process exit code. Exits on empty line or Ctrl-D.
    """
    load_environment()
    client = LLMClient()
    conv = Conversation(client, system=system, model=model)

    print("Chat session (blank line or Ctrl-D to exit).")
    while True:
        try:
            line = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not line.strip():
            return 0
        try:
            reply = conv.run(line.strip(), model=model) if model else conv.run(line.strip())
        except Exception as exc:  # keep the loop alive on transient errors
            print(f"assistant> [error] {exc}")
            continue
        print(f"assistant> {reply}")


def run_agent_repl(
    *,
    model: str | None = None,
    system: str = "You are a helpful assistant.",
) -> int:
    """Run an interactive ReAct agent shell against the configured endpoint.

    Registers built-in read-only tools so the model can call them. Returns
    process exit code. Exits on empty line or Ctrl-D.
    """
    load_environment()
    client = LLMClient()
    registry = ToolRegistry()
    register_builtins(registry)
    agent = Agent(client, registry, system=system, model=model)

    print("Agent session (built-in tools enabled; blank line or Ctrl-D to exit).")
    while True:
        try:
            line = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not line.strip():
            return 0
        try:
            reply = agent.run(line.strip())
        except Exception as exc:  # keep the loop alive on transient errors
            print(f"agent> [error] {exc}")
            continue
        print(f"agent> {reply}")


def cli(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    model = None
    use_agent = False
    if "--model" in argv:
        model = argv[argv.index("--model") + 1]
    if "--agent" in argv:
        use_agent = True
    if use_agent:
        return run_agent_repl(model=model)
    return run_repl(model=model)