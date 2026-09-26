from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from figura.providers import (
    MODEL_IDS,
    FinishReason,
    FunctionTool,
    ImageBlock,
    InstructionBlock,
    InstructionRole,
    MessageRole,
    ProviderCallError,
    ProviderContinuation,
    ProviderFactory,
    ProviderFailureCode,
    ProviderId,
    ProviderInputError,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderToolCall,
    TextBlock,
)


_TOOLS = (
    FunctionTool(
        name="inspect_chart",
        description="Inspect a chart.",
        parameters={
            "type": "object",
            "properties": {"focus": {"type": "string"}},
            "required": ["focus"],
        },
    ),
)


class FakeTransport:
    def __init__(self, response: object | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def create(self, **payload: object) -> object:
        self.calls.append(payload)
        if self.error is not None:
            raise self.error
        return self.response


def _response(
    *,
    content: str = "ok",
    reasoning: str = "",
    tool_calls: tuple[object, ...] = (),
    finish_reason: str = "stop",
) -> object:
    message = SimpleNamespace(
        content=content,
        reasoning_content=reasoning or None,
        tool_calls=tool_calls,
    )
    return SimpleNamespace(
        id="response-1",
        choices=(SimpleNamespace(index=0, message=message, finish_reason=finish_reason),),
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17),
    )


def _call(name: str, call_id: str, arguments: str) -> object:
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _environment() -> dict[str, str]:
    return {
        "FIGURA_QWEN_API_KEY": "qwen-secret",
        "FIGURA_QWEN_BASE_URL": "https://qwen.example.test/compatible-mode/v1",
        "FIGURA_DEEPSEEK_API_KEY": "deepseek-secret",
        "FIGURA_MIMO_API_KEY": "mimo-secret",
    }


def _factory(transport: FakeTransport, environ: dict[str, str] | None = None) -> ProviderFactory:
    return ProviderFactory.from_env(
        _environment() if environ is None else environ,
        transport_factory=lambda _profile: transport,
    )


def _request(
    provider_id: ProviderId,
    *,
    instructions: tuple[InstructionBlock, ...] = (),
    messages: tuple[ProviderMessage, ...] | None = None,
    tools: tuple[FunctionTool, ...] = (),
    stream: bool = False,
    thinking_mode: bool | None = None,
) -> ProviderRequest:
    return ProviderRequest(
        provider_id=provider_id,
        model_id=MODEL_IDS[provider_id],
        instructions=instructions,
        messages=messages or (ProviderMessage(MessageRole.USER, "hello"),),
        options=ProviderOptions(
            max_completion_tokens=256,
            stream=stream,
            thinking_mode=thinking_mode,
        ),
        tools=tools,
    )


def test_allowlist_and_configuration_only_availability() -> None:
    factory = _factory(FakeTransport(), {**_environment(), "FIGURA_QWEN_BASE_URL": ""})

    availability = {item.provider_id: item for item in factory.availability()}

    assert MODEL_IDS == {
        ProviderId.QWEN: "qwen3.8-flash",
        ProviderId.DEEPSEEK: "deepseek-flash",
        ProviderId.MIMO: "mimo-v2.6-flash",
    }
    assert not availability[ProviderId.QWEN].available
    assert availability[ProviderId.QWEN].reason_code == "configuration_missing"
    assert availability[ProviderId.DEEPSEEK].available
    assert availability[ProviderId.MIMO].available
    assert all("secret" not in repr(item) for item in availability.values())


def test_factory_requires_explicit_allowlisted_pair_and_never_falls_back() -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)

    with pytest.raises(ProviderInputError) as unsupported_provider:
        factory.create("other", "some-model")
    assert unsupported_provider.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_PROVIDER

    with pytest.raises(ProviderInputError) as unsupported_model:
        factory.create(ProviderId.QWEN, "deepseek-flash")
    assert unsupported_model.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_MODEL
    assert not transport.calls


@pytest.mark.parametrize(
    ("provider_id", "thinking_key"),
    [
        (ProviderId.QWEN, "preserve_thinking"),
        (ProviderId.DEEPSEEK, "thinking"),
        (ProviderId.MIMO, "thinking"),
    ],
)
def test_each_provider_maps_instructions_images_tools_and_thinking(
    provider_id: ProviderId, thinking_key: str
) -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)
    request = _request(
        provider_id,
        instructions=(
            InstructionBlock(InstructionRole.SYSTEM, "System rule."),
            InstructionBlock(InstructionRole.DEVELOPER, "Developer rule."),
        ),
        messages=(
            ProviderMessage(
                MessageRole.USER,
                (TextBlock("Read this chart."), ImageBlock("image/png", b"png-data")),
            ),
        ),
        tools=_TOOLS,
    )

    factory.create(provider_id, MODEL_IDS[provider_id]).complete(request)

    payload = transport.calls[0]
    assert payload["model"] == MODEL_IDS[provider_id]
    assert payload["max_completion_tokens"] == 256
    assert payload["messages"][0]["role"] == "system"
    expected_second_instruction_role = (
        "developer" if provider_id is ProviderId.MIMO else "system"
    )
    assert payload["messages"][1] == {
        "role": expected_second_instruction_role,
        "content": "Developer rule.",
    }
    image_part = payload["messages"][2]["content"][1]
    encoded = image_part["image_url"]["url"].split(",", 1)[1]
    assert base64.b64decode(encoded) == b"png-data"
    assert payload["tools"][0]["function"]["name"] == "inspect_chart"
    assert payload["tool_choice"] == "auto"
    if provider_id is ProviderId.QWEN:
        assert payload["extra_body"][thinking_key] is True
    else:
        assert payload["extra_body"][thinking_key] == {"type": "enabled"}


@pytest.mark.parametrize("provider_id", [ProviderId.DEEPSEEK, ProviderId.MIMO])
def test_thinking_tool_history_replays_private_continuation(provider_id: ProviderId) -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)
    tool_call = ProviderToolCall("call-1", "inspect_chart", '{"focus":"legend"}')
    request = _request(
        provider_id,
        messages=(
            ProviderMessage(MessageRole.USER, "Inspect the legend."),
            ProviderMessage(
                MessageRole.ASSISTANT,
                "",
                tool_calls=(tool_call,),
                continuation=ProviderContinuation(provider_id, 1, "private plan"),
            ),
            ProviderMessage(MessageRole.TOOL, "Legend is at top.", tool_call_id="call-1"),
        ),
        tools=_TOOLS,
    )

    factory.create(provider_id, MODEL_IDS[provider_id]).complete(request)

    assert transport.calls[0]["messages"][1]["reasoning_content"] == "private plan"
    assert "private plan" not in repr(request.messages[1])


@pytest.mark.parametrize("provider_id", [ProviderId.DEEPSEEK, ProviderId.MIMO])
def test_missing_required_thinking_continuation_is_rejected_before_transport(
    provider_id: ProviderId,
) -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)
    request = _request(
        provider_id,
        messages=(
            ProviderMessage(MessageRole.USER, "Inspect the legend."),
            ProviderMessage(
                MessageRole.ASSISTANT,
                "",
                tool_calls=(ProviderToolCall("call-1", "inspect_chart", "{}"),),
            ),
            ProviderMessage(MessageRole.TOOL, "done", tool_call_id="call-1"),
        ),
        tools=_TOOLS,
    )

    with pytest.raises(ProviderInputError) as error:
        factory.create(provider_id, MODEL_IDS[provider_id]).complete(request)

    assert error.value.failure.failure_code is ProviderFailureCode.INVALID_REQUEST
    assert not transport.calls


def test_unsupported_schema_and_qwen_strict_mode_are_rejected_before_transport() -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)
    invalid_schema = FunctionTool(
        name="inspect_chart",
        parameters={
            "type": "object",
            "patternProperties": {".*": {"type": "string"}},
        },
    )
    strict_schema = FunctionTool(
        name="inspect_chart",
        parameters={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        strict=True,
    )

    with pytest.raises(ProviderInputError) as invalid_error:
        factory.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]).complete(
            _request(ProviderId.DEEPSEEK, tools=(invalid_schema,))
        )
    with pytest.raises(ProviderInputError) as strict_error:
        factory.create(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN]).complete(
            _request(ProviderId.QWEN, tools=(strict_schema,))
        )

    assert invalid_error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY
    assert strict_error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY
    assert not transport.calls


def test_deepseek_strict_requires_beta_endpoint_and_all_functions_strict() -> None:
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    strict_tool = FunctionTool("inspect_chart", schema, strict=True)
    transport = FakeTransport(_response())
    regular_factory = _factory(transport)

    with pytest.raises(ProviderInputError) as regular_endpoint_error:
        regular_factory.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]).complete(
            _request(ProviderId.DEEPSEEK, tools=(strict_tool,))
        )
    assert regular_endpoint_error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY

    beta_factory = _factory(
        transport,
        {**_environment(), "FIGURA_DEEPSEEK_BASE_URL": "https://api.deepseek.com/beta"},
    )
    with pytest.raises(ProviderInputError) as mixed_error:
        beta_factory.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]).complete(
            _request(ProviderId.DEEPSEEK, tools=(strict_tool, _TOOLS[0]))
        )
    assert mixed_error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY

    beta_factory.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]).complete(
        _request(ProviderId.DEEPSEEK, tools=(strict_tool,))
    )
    assert len(transport.calls) == 1


def test_mimo_strict_requires_closed_objects_and_all_declared_properties_required() -> None:
    transport = FakeTransport(_response())
    factory = _factory(transport)
    invalid = FunctionTool(
        "inspect_chart",
        {
            "type": "object",
            "properties": {"focus": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
        strict=True,
    )
    valid = FunctionTool(
        "inspect_chart",
        {
            "type": "object",
            "properties": {"focus": {"type": "string"}},
            "required": ["focus"],
            "additionalProperties": False,
        },
        strict=True,
    )

    with pytest.raises(ProviderInputError) as strict_error:
        factory.create(ProviderId.MIMO, MODEL_IDS[ProviderId.MIMO]).complete(
            _request(ProviderId.MIMO, tools=(invalid,))
        )
    assert strict_error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY

    factory.create(ProviderId.MIMO, MODEL_IDS[ProviderId.MIMO]).complete(
        _request(ProviderId.MIMO, tools=(valid,))
    )
    assert len(transport.calls) == 1


def test_nonstreaming_response_normalizes_order_usage_and_hides_continuation() -> None:
    transport = FakeTransport(
        _response(
            content="visible",
            reasoning="private continuation",
            tool_calls=(
                _call("inspect_chart", "call-2", '{"focus":"legend"}'),
                _call("inspect_chart", "call-1", '{"focus":"title"}'),
            ),
            finish_reason="tool_calls",
        )
    )
    result = _factory(transport).create(ProviderId.QWEN, MODEL_IDS[ProviderId.QWEN]).complete(
        _request(ProviderId.QWEN)
    )

    assert result.assistant_content == "visible"
    assert result.finish_reason is FinishReason.TOOL_CALLS
    assert [call.call_id for call in result.tool_calls] == ["call-2", "call-1"]
    assert result.usage.prompt_tokens == 12
    assert result.continuation is not None
    assert result.continuation.reasoning_content == "private continuation"
    assert "private continuation" not in repr(result)
    assert "private continuation" not in repr(result.to_public_dict())


def test_streaming_response_normalizes_text_and_interleaved_tool_calls() -> None:
    events = (
        SimpleNamespace(
            id="stream-1",
            choices=(
                SimpleNamespace(
                    index=0,
                    delta=SimpleNamespace(
                        content="answer",
                        reasoning_content="private",
                        tool_calls=(
                            SimpleNamespace(
                                index=1,
                                id="call-1",
                                function=SimpleNamespace(name="inspect_chart", arguments='{"focus":"'),
                            ),
                        ),
                    ),
                    finish_reason=None,
                ),
            ),
            usage=None,
        ),
        SimpleNamespace(
            id="stream-1",
            choices=(
                SimpleNamespace(
                    index=0,
                    delta=SimpleNamespace(
                        content=None,
                        reasoning_content=None,
                        tool_calls=(
                            SimpleNamespace(
                                index=0,
                                id="call-0",
                                function=SimpleNamespace(name="other_tool", arguments="{}"),
                            ),
                            SimpleNamespace(
                                index=1,
                                id=None,
                                function=SimpleNamespace(name=None, arguments='legend"}'),
                            ),
                        ),
                    ),
                    finish_reason="tool_calls",
                ),
            ),
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=8, total_tokens=18),
        ),
    )
    transport = FakeTransport(events)
    result = _factory(transport).create(ProviderId.MIMO, MODEL_IDS[ProviderId.MIMO]).complete(
        _request(ProviderId.MIMO, stream=True)
    )

    assert result.assistant_content == "answer"
    assert result.finish_reason is FinishReason.TOOL_CALLS
    assert [call.call_id for call in result.tool_calls] == ["call-0", "call-1"]
    assert result.tool_calls[1].arguments == '{"focus":"legend"}'
    assert result.usage.total_tokens == 18
    assert result.continuation is not None
    assert result.continuation.reasoning_content == "private"


def test_failure_classification_is_safe_and_does_not_retry_unknown_outcome() -> None:
    transport = FakeTransport(error=RuntimeError("secret key and raw endpoint"))
    factory = _factory(transport)

    with pytest.raises(ProviderCallError) as error:
        factory.create(ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]).complete(
            _request(ProviderId.DEEPSEEK)
        )

    assert error.value.failure.failure_code is ProviderFailureCode.TRANSPORT_ERROR
    assert not error.value.failure.outcome_known
    assert "secret" not in str(error.value)
    assert len(transport.calls) == 1


def test_http_rejection_is_classified_without_provider_body() -> None:
    request = httpx.Request("POST", "https://secret.example.test/chat/completions")
    response = httpx.Response(400, request=request)
    transport = FakeTransport(error=APIStatusError("raw secret body", response=response, body={"key": "secret"}))

    with pytest.raises(ProviderCallError) as error:
        _factory(transport).create(
            ProviderId.DEEPSEEK, MODEL_IDS[ProviderId.DEEPSEEK]
        ).complete(_request(ProviderId.DEEPSEEK))

    assert error.value.failure.failure_code is ProviderFailureCode.PROVIDER_REJECTED
    assert error.value.failure.outcome_known
    assert error.value.failure.http_status == 400
    assert "secret" not in str(error.value)


def test_mimo_custom_token_plan_url_and_key_are_used_as_a_profile_pair() -> None:
    transport = FakeTransport(_response())
    env = {
        **_environment(),
        "FIGURA_MIMO_BASE_URL": "https://token-plan.example.test/openai/v1",
        "FIGURA_MIMO_API_KEY": "token-plan-key",
        "FIGURA_MIMO_TIMEOUT_SECONDS": "90",
        "FIGURA_MIMO_THINKING_MODE": "false",
    }
    captured_profiles = []
    factory = ProviderFactory.from_env(
        env,
        transport_factory=lambda profile: (captured_profiles.append(profile) or transport),
    )

    client = factory.create(ProviderId.MIMO, MODEL_IDS[ProviderId.MIMO])
    client.complete(_request(ProviderId.MIMO))

    profile = captured_profiles[0]
    assert profile.base_url == "https://token-plan.example.test/openai/v1"
    assert profile.api_key == "token-plan-key"
    assert profile.timeout_seconds == 90
    assert transport.calls[0]["extra_body"]["thinking"] == {"type": "disabled"}
