"""Interact access programmatically via an in-memory conversation.

Simple read-a-line → reply → repeat loop; history stays in memory.
"""

from __future__ import annotations

import sys

from .conversation import Conversation
from .client import LLMClient, load_environment


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


def cli(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    model = None
    if "--model" in argv:
        model = argv[argv.index("--model") + 1]
    return run_repl(model=model)