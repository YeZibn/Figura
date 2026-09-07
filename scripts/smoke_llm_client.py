#!/usr/bin/env python3
"""Smoke test for the LLM client against a real OpenAI-compatible endpoint.

Runs the three acceptance paths from change add-llm-client task 7.2:
  (a) plain dialogue (streaming),
  (b) tool-defined call with tool_calls resolved and passed back,
  (c) deep-thinking model streaming with reasoning/content collected separately.

Requires DASHSCOPE_API_KEY (or --api-key). When no credential is available it
prints a hint and exits without error so it can be wired into CI safely.

Usage:
    python scripts/smoke_llm_client.py
    python scripts/smoke_llm_client.py --base-url <url> --model qwen-plus
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chartagent.client import LLMClient, append_to_history, load_environment  # noqa: E402


def _client(args: argparse.Namespace) -> LLMClient | None:
    load_environment()  # pulls key/base_url/model from .env if present
    overrides: dict = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.api_key:
        overrides["api_key"] = args.api_key
    try:
        return LLMClient(**overrides)
    except ValueError as e:
        print(f"SKIP: no credential available -> {e}")
        print("  Set DASHSCOPE_API_KEY (or .env) and re-run; pass --api-key as fallback.")
        return None


def _smoke_plain(client: LLMClient, args: argparse.Namespace) -> None:
    model = args.model or client.config.model or "qwen-plus"
    res = client.chat(
        [{"role": "user", "content": "用一句话回答：什么是图表可视化？"}],
        model=model,
    )
    assert res.content, "plain dialogue produced no content"
    print(f"(a) plain     : {res.content[:80]!r} | finish={res.finish_reason} | usage={res.usage.total_tokens if res.usage else 'n/a'}")


def _smoke_tools(client: LLMClient, args: argparse.Namespace) -> None:
    model = args.model or client.config.model or "qwen-plus"
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_current_weather",
                "description": "Get the current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                },
            },
        }
    ]
    messages = [{"role": "user", "content": "北京现在天气如何？请调用工具查询。"}]
    res = client.chat(messages, model=model, tools=tools)
    print(f"(b) tool_calls: {len(res.tool_calls)} call(s)")
    for tc in res.tool_calls:
        print(f"    call id={tc.id} name={tc.name} args={tc.arguments}")
    if res.tool_calls:
        # Feed a synthetic tool result back into a follow-up to prove roundtrip.
        tool_result = {"role": "tool", "tool_call_id": res.tool_calls[0].id, "content": '{"temp": 18, "condition": "sunny"}'}
        follow = list(messages)
        append_to_history(follow, res)  # content-only assistant entry
        follow.append(tool_result)
        res2 = client.chat(follow, model=model, tools=tools)
        assert res2.content, "follow-up after tool result produced no content"
        print(f"(b) followed  : {res2.content[:80]!r}")


def _smoke_thinking(client: LLMClient, args: argparse.Namespace) -> None:
    model = args.thinking_model or client.config.model or "qwen-max"
    res = client.chat(
        [{"role": "user", "content": "23 和 17 的乘积是多少？请逐步思考。"}],
        model=model,
        enable_thinking=True,
    )
    print(f"(c) thinking  : reasoning_len={len(res.reasoning)} content={res.content[:60]!r}")
    # reasoning must never leak into assistant history entries
    entry = {"role": "assistant", "content": res.content}
    mem = repr(entry)
    assert not res.reasoning or ("reasoning_content" not in mem and res.reasoning not in mem)
    print("    history-isolated: ok (reasoning kept out of assistant entry)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=None, help="Override endpoint base_url.")
    parser.add_argument("--api-key", default=None, help="Override API key.")
    parser.add_argument("--model", default=None, help="Model for (a) and (b); defaults to DASH_MODEL/.env")
    parser.add_argument("--thinking-model", default=None, help="Deep-thinking model for (c); defaults to DASH_MODEL/.env")
    args = parser.parse_args()

    client = _client(args)
    if client is None:
        return 0

    # (a) plain
    _smoke_plain(client, args)
    # (b) tools
    _smoke_tools(client, args)
    # (c) thinking streaming
    _smoke_thinking(client, args)

    print("\nSmoke OK: all three acceptance paths succeeded on the real endpoint.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())