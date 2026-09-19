"""Interact access programmatically via an in-memory conversation.

Simple read-a-line → reply → repeat loop; history stays in memory. Two
interaction modes: the default ``Conversation`` chat REPL, and a tool-capable
``Agent`` ReAct REPL selected via ``--agent``. In the agent REPL, an ``@path``
or ``@"path with spaces"`` token attaches a local image to that turn as
multimodal content.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import IO, Optional

from .agent import Agent
from .conversation import Conversation
from .client import LLMClient, load_environment
from .multimodal import build_registered_attachment_turn
from .memory import SQLiteAgentMemory
from .runtime import AGENT_SYSTEM_PROMPT, AgentRuntime, create_agent_runtime
from .storage import StorageRootConflict, resolve_storage_paths
from .trace import JsonlTraceRenderer, TextTraceRenderer, TraceSink
from .tools import ToolRegistry
from .tools.builtins import register_builtins
from .tools.chart import register_chart_tools

_IMAGE_REF = re.compile(r'@"([^"\r\n]+)"|@(?!")(\S+)')


def extract_image_refs(line: str) -> tuple[str, list[str]]:
    """Split input into normalized text and quoted/unquoted image paths."""
    paths = [match.group(1) or match.group(2) for match in _IMAGE_REF.finditer(line)]
    text = _IMAGE_REF.sub("", line)
    text = re.sub(r"\s+", " ", text).strip()
    return text, paths


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
    system: str = AGENT_SYSTEM_PROMPT,
    trace: bool = False,
    trace_reasoning: bool = False,
    trace_format: str = "text",
    trace_stream: Optional[IO[str]] = None,
    session_name: str | None = None,
    data_dir: str | None = None,
) -> int:
    """Run an interactive ReAct agent shell against the configured endpoint.

    Registers built-in read-only tools so the model can call them. Returns
    process exit code. Exits on empty line or Ctrl-D.
    """
    if trace_reasoning and not trace:
        raise ValueError("--trace-reasoning requires --trace")
    if trace_format not in {"text", "json", "jsonl"}:
        raise ValueError("trace_format must be text, json, or jsonl")

    trace_sink: Optional[TraceSink] = None
    if trace:
        renderer = (
            JsonlTraceRenderer(trace_stream)
            if trace_format in {"json", "jsonl"}
            else TextTraceRenderer(trace_stream)
        )
        trace_sink = renderer
    runtime_kwargs = {
        "model": model,
        "system": system,
        "trace_sink": trace_sink,
        "trace_reasoning": trace_reasoning,
        "session_name": session_name,
        "load_env": load_environment,
        "llm_client_cls": LLMClient,
        "agent_cls": Agent,
        "registry_cls": ToolRegistry,
        "register_builtins_fn": register_builtins,
        "register_chart_tools_fn": register_chart_tools,
    }
    if data_dir is not None:
        runtime_kwargs["database"] = resolve_storage_paths(data_dir=data_dir).database
    try:
        runtime = create_agent_runtime(
            **runtime_kwargs,
        )
    except StorageRootConflict as exc:
        print(f"agent> [storage error] {exc}", file=sys.stderr)
        return 2
    agent = runtime.agent
    attachments = runtime.attachments

    print("Agent session (built-in tools enabled; blank line or Ctrl-D to exit).")
    while True:
        try:
            line = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0
        if not line.strip():
            return 0
        stripped = line.strip()
        text, image_paths = extract_image_refs(stripped)
        try:
            if image_paths:
                metadata = [attachments.register(path).metadata() for path in image_paths]
                turn = build_registered_attachment_turn(text, metadata)
            else:
                turn = stripped  # no @: byte-identical to the old behavior
            reply = agent.run(turn)
        except Exception as exc:  # bad @path or transient error: keep session
            print(f"agent> [error] {exc}")
            continue
        print(f"agent> {reply}")


def cli(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="python -m chartagent")
    parser.add_argument("--agent", action="store_true", help="use the tool-capable Agent REPL")
    parser.add_argument("--model", default=None)
    parser.add_argument("--trace", action="store_true", help="show Agent execution trace")
    parser.add_argument(
        "--trace-reasoning",
        action="store_true",
        help="show provider-returned reasoning in the Agent trace",
    )
    parser.add_argument(
        "--trace-format",
        choices=("text", "json", "jsonl"),
        default="text",
        help="Agent trace renderer (text or JSONL)",
    )
    parser.add_argument("--session", default=None, help="resume or create a named Agent session")
    parser.add_argument("--new-session", default=None, help="create a fresh named Agent session")
    parser.add_argument("--list-sessions", action="store_true", help="list named Agent sessions and exit")
    parser.add_argument("--delete-session", default=None, help="delete a named Agent session after confirmation")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="durable data root; relative paths are resolved from the project root",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)

    trace_flags_used = args.trace or args.trace_reasoning or args.trace_format != "text"
    if trace_flags_used and not args.agent:
        print("error: trace options require --agent", file=sys.stderr)
        return 2
    if args.trace_reasoning and not args.trace:
        print("error: --trace-reasoning requires --trace", file=sys.stderr)
        return 2
    if args.trace_format != "text" and not args.trace:
        print("error: --trace-format requires --trace", file=sys.stderr)
        return 2
    requested = [args.session, args.new_session, args.delete_session]
    if args.list_sessions or any(value is not None for value in requested):
        if not args.agent:
            print("error: session options require --agent", file=sys.stderr)
            return 2
        if args.data_dir is None:
            load_environment()
        try:
            database = (
                resolve_storage_paths(data_dir=args.data_dir).database
                if args.data_dir is not None
                else None
            )
        except StorageRootConflict as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if sum(value is not None for value in requested) + int(args.list_sessions) > 1:
            print("error: session options are mutually exclusive", file=sys.stderr)
            return 2
        try:
            if args.list_sessions:
                for item in SQLiteAgentMemory.list_sessions(database=database):
                    print(f"{item.name}\t{item.updated_at}")
                return 0
            if args.delete_session is not None:
                answer = input(f"Delete session {args.delete_session!r}? [y/N] ")
                if answer.strip().lower() not in {"y", "yes"}:
                    return 0
                return 0 if SQLiteAgentMemory.delete_session(args.delete_session, database=database) else 1
            if args.new_session is not None:
                if any(item.name == args.new_session for item in SQLiteAgentMemory.list_sessions(database=database)):
                    print(f"error: session already exists: {args.new_session}", file=sys.stderr)
                    return 2
                session_name = args.new_session
            else:
                session_name = args.session
        except StorageRootConflict as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        session_name = None
    if args.agent:
        return run_agent_repl(
            model=args.model,
            trace=args.trace,
            trace_reasoning=args.trace_reasoning,
            trace_format=args.trace_format,
            **({"session_name": session_name} if session_name is not None else {}),
            **({"data_dir": args.data_dir} if args.data_dir is not None else {}),
        )
    return run_repl(model=args.model)
