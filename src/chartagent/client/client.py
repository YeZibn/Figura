"""The thin controllable client layer over the ``openai`` SDK.

Responsibilities (all provider quirk handling is owned here, never by callers):
- Normalize every call into a single :class:`NormalizedResult`.
- Capture non-standard reasoning into ``reasoning`` but keep it out of history.
- Build assistant history entries containing only ``content`` (never reasoning).
- Send standard Chat Completions knobs such as ``reasoning_effort``.
- Honor explicit retry/timeout and emit one structured observation per call.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, List, Mapping, Optional, Sequence

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import ClientConfig, resolve_config
from .models import NormalizedResult, ToolCall
from ..trace import TraceEmitter, TraceSink

logger = logging.getLogger(__name__)

# Callables the layer may override in tests / mocks.
_CompletionFactory = Callable[..., Any]

ObservationSink = Callable[[Mapping[str, Any]], None]

# Inject point for tests to swap the transport without real HTTP.
_openai_factory: _CompletionFactory = OpenAI


def _safe_exception_type(error: BaseException) -> str:
    """Return bounded exception metadata without copying provider details."""
    return (type(error).__name__ or "Exception")[:64]


def _default_observation_sink(entry: Mapping[str, Any]) -> None:
    """Emit a sanitized observation entry via stdlib logging (no secrets)."""
    logger.info("llm_call provider=%s model=%s", entry.get("provider"), entry.get("model"))


# --------------------------------------------------------------------------- #
# History construction contract
# --------------------------------------------------------------------------- #
def assistant_history_entry(result: NormalizedResult) -> ChatCompletionMessageParam:
    """Assistant-side history entry containing ONLY content, never reasoning.

    Echoing reasoning back (e.g. ``reasoning_content``) breaks deep-thinking
    providers with a 400, so this is the single point that strips it.
    """
    return {"role": "assistant", "content": result.content}


def append_to_history(
    messages: List[ChatCompletionMessageParam],
    result: NormalizedResult,
) -> List[ChatCompletionMessageParam]:
    """Append the assistant reply (content only) to an in-progress history."""
    messages.append(assistant_history_entry(result))  # type: ignore[arg-type]
    return messages


# --------------------------------------------------------------------------- #
# Normalization
# --------------------------------------------------------------------------- #
def _non_streaming_tool_calls(message: Any) -> List[ToolCall]:
    calls = []
    for tc in getattr(message, "tool_calls", None) or []:
        calls.append(
            ToolCall(
                id=tc.id or "",
                name=tc.function.name or "",
                arguments=tc.function.arguments or "",
            )
        )
    return calls


def _reasoning_of(msg: Any) -> str:
    # Some compatible services expose this optional, non-standard field.
    return getattr(msg, "reasoning_content", None) or ""


def _usage_value(usage: Any, name: str) -> Any:
    if isinstance(usage, Mapping):
        return usage.get(name)
    return getattr(usage, name, None)


def _numeric_usage_value(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _usage_summary(usage: Any) -> Optional[dict[str, int | float]]:
    """Keep only bounded numeric token counters for observation logs."""
    if usage is None:
        return None
    summary: dict[str, int | float] = {}
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _numeric_usage_value(_usage_value(usage, name))
        if value is not None:
            summary[name] = value
    details = _usage_value(usage, "completion_tokens_details")
    reasoning_tokens = _numeric_usage_value(
        _usage_value(details, "reasoning_tokens") if details is not None else None
    )
    if reasoning_tokens is not None:
        summary["reasoning_tokens"] = reasoning_tokens
    return summary


def normalize_non_streaming(completion: Any) -> NormalizedResult:
    choice = completion.choices[0]
    message = choice.message
    return NormalizedResult(
        content=message.content or "",
        reasoning=_reasoning_of(message),
        tool_calls=_non_streaming_tool_calls(message),
        finish_reason=getattr(choice, "finish_reason", None),
        usage=getattr(completion, "usage", None),
        raw=completion,
    )


def _collect_streaming_deltas(stream: Any) -> NormalizedResult:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: dict[int, dict[str, str]] = {}
    finish_reason: Optional[str] = None
    usage: Any = None
    raw_chunks: list[Any] = []

    for chunk in stream:
        raw_chunks.append(chunk)
        if not chunk.choices:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            continue
        delta = chunk.choices[0].delta
        if getattr(delta, "reasoning_content", None):
            reasoning_parts.append(delta.reasoning_content)
        if getattr(delta, "content", None):
            content_parts.append(delta.content)
        for tc in getattr(delta, "tool_calls", None) or []:
            entry = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            if tc.id:
                entry["id"] += tc.id
            if tc.function and tc.function.name:
                entry["name"] += tc.function.name
            if tc.function and tc.function.arguments:
                entry["arguments"] += tc.function.arguments
        if getattr(chunk.choices[0], "finish_reason", None):
            finish_reason = chunk.choices[0].finish_reason

    ordered = [e for _, e in sorted(tool_calls.items(), key=lambda kv: kv[0])]
    tool_calls_list = [
        ToolCall(id=e["id"], name=e["name"], arguments=e["arguments"])
        for e in ordered
    ]
    return NormalizedResult(
        content="".join(content_parts),
        reasoning="".join(reasoning_parts),
        tool_calls=tool_calls_list,
        finish_reason=finish_reason,
        usage=usage,
        raw=raw_chunks,
    )


# --------------------------------------------------------------------------- #
# The client
# --------------------------------------------------------------------------- #
class LLMClient:
    """OpenAI-compatible LLM client with the controllable layer applied."""

    def __init__(
        self,
        config: Optional[ClientConfig] = None,
        *,
        observe: Optional[ObservationSink] = None,
        trace_sink: Optional[TraceSink] = None,
        trace_run_id: Optional[str] = None,
        **overrides: Any,
    ) -> None:
        if overrides:
            resolved_overrides = dict(overrides)
            # An explicit ``None`` is useful to assert that no credential is
            # available. Keep the no-override path environment-aware for the
            # normal CLI/runtime startup flow.
            if "api_key" in resolved_overrides and resolved_overrides["api_key"] is None:
                resolved_overrides["api_key"] = ""
            resolved = resolve_config(**resolved_overrides)
        else:
            resolved = config or resolve_config()
        self.config = resolved
        if not self.config.api_key:
            raise ValueError(f"An API key is required for provider {self.config.provider}.")
        self._observe = observe or _default_observation_sink
        self._trace = (
            TraceEmitter(trace_sink, run_id=trace_run_id)
            if trace_sink is not None
            else None
        )
        self._sdk = _connect_sdk(self.config, _openai_factory)

    # -- calls -------------------------------------------------------------- #
    def chat(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        *,
        model: Optional[str] = None,
        tools: Optional[Sequence[Any]] = None,
        stream: bool = True,
        reasoning_effort: Optional[str] = None,
        max_completion_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        trace_sink: Optional[TraceSink] = None,
        trace_run_id: Optional[str] = None,
        trace_turn: Optional[int] = None,
    ) -> NormalizedResult:
        cfg = self.config
        use_model = model or cfg.model
        if not use_model:
            raise ValueError("A model must be specified (call-time or config).")

        request: dict[str, Any] = {
            "model": use_model,
            "messages": list(messages),
            "stream": stream,
        }
        if stream and cfg.provider == "openai":
            # The SDK omits usage on streaming unless explicitly requested.
            request["stream_options"] = {"include_usage": True}
        if tools:
            request["tools"] = tools
        if max_completion_tokens is not None:
            request["max_completion_tokens"] = max_completion_tokens
        if temperature is not None:
            request["temperature"] = temperature
        effort = reasoning_effort if reasoning_effort is not None else cfg.reasoning_effort
        if cfg.provider == "openai" and effort is not None:
            request["reasoning_effort"] = effort
        if cfg.provider == "qwen" and cfg.enable_thinking:
            request["extra_body"] = {"enable_thinking": True}

        trace = self._trace
        if trace_sink is not None:
            trace = (
                trace_sink
                if isinstance(trace_sink, TraceEmitter)
                else TraceEmitter(trace_sink, run_id=trace_run_id)
            )
        if trace is not None:
            trace.emit(
                "model_started",
                turn=trace_turn,
                provider=cfg.provider,
                model=use_model,
                message_count=len(messages),
                tool_count=len(tools or ()),
                stream=stream,
            )

        started = time.monotonic()
        try:
            completion = self._sdk.chat.completions.create(**request)
        except Exception as exc:
            if trace is not None:
                trace.emit(
                    "model_completed",
                    turn=trace_turn,
                    provider=cfg.provider,
                    model=use_model,
                    status="error",
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    error_code="provider_request_failed",
                    error_type=_safe_exception_type(exc),
                )
            raise
        result = _collect_streaming_deltas(completion) if stream else normalize_non_streaming(completion)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._emit_observation(result, use_model, elapsed_ms)
        if trace is not None:
            trace.emit(
                "model_completed",
                turn=trace_turn,
                provider=cfg.provider,
                model=use_model,
                status="ok",
                elapsed_ms=elapsed_ms,
                finish_reason=result.finish_reason,
                content_length=len(result.content),
                reasoning_available=bool(result.reasoning),
                tool_calls=len(result.tool_calls),
                usage_available=result.usage is not None,
            )
        return result

    # -- observation -------------------------------------------------------- #
    def _emit_observation(
        self,
        result: NormalizedResult,
        model: str,
        elapsed_ms: int,
    ) -> None:
        entry = {
            "provider": self.config.provider,
            "model": model,
            "elapsed_ms": elapsed_ms,
            "finish_reason": result.finish_reason,
            "content_len": len(result.content),
            "reasoning_len": len(result.reasoning),
            "tool_calls": len(result.tool_calls),
            "usage": _usage_summary(result.usage),
            "usage_available": result.usage is not None,
        }
        self._observe(entry)


def _connect_sdk(config: ClientConfig, factory: _CompletionFactory) -> Any:
    return factory(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout,
        max_retries=config.max_retries,
    )
