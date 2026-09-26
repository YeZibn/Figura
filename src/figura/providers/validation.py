"""Local validation for bounded provider-neutral requests."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from ..json_schema import (
    JsonValueError,
    SchemaDefinitionError,
    canonical_json_dumps,
    validate_schema_definition,
)
from .errors import ProviderFailure, ProviderFailureCode, ProviderInputError
from .models import (
    FunctionTool,
    ImageBlock,
    InstructionBlock,
    InstructionRole,
    MessageRole,
    MODEL_IDS,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderRequest,
    ProviderOptions,
    ProviderToolCall,
    TextBlock,
)


MAX_COMPLETION_TOKENS = 131_072
MAX_MESSAGE_COUNT = 256
MAX_INSTRUCTION_COUNT = 32
MAX_TOOL_COUNT = 64
MAX_TOOL_CALLS_PER_RESPONSE = 64
MAX_TOTAL_TEXT_BYTES = 1_048_576
MAX_IMAGE_COUNT = 16
MAX_IMAGE_BYTES = 24 * 1024 * 1024 - 64
MAX_TOTAL_IMAGE_BYTES = 32 * 1024 * 1024
SUPPORTED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
def fail(
    code: ProviderFailureCode,
    safe_message: str,
    *,
    known: bool = True,
    transient: bool = False,
) -> ProviderInputError:
    return ProviderInputError(
        ProviderFailure(
            failure_code=code,
            outcome_known=known,
            transient=transient,
            safe_message=safe_message,
        )
    )


def coerce_provider_id(value: ProviderId | str) -> ProviderId:
    try:
        return value if isinstance(value, ProviderId) else ProviderId(value)
    except (TypeError, ValueError):
        raise fail(ProviderFailureCode.UNSUPPORTED_PROVIDER, "不支持所选模型服务商。") from None


def validate_request(request: ProviderRequest, expected_provider: ProviderId) -> None:
    provider_id = coerce_provider_id(request.provider_id)
    if provider_id is not expected_provider:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "请求的模型服务商与客户端配置不匹配。")
    if request.model_id != MODEL_IDS[provider_id]:
        raise fail(ProviderFailureCode.UNSUPPORTED_MODEL, "该模型不在此服务商的允许列表中。")
    options = request.options
    if not isinstance(options, ProviderOptions):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "模型请求必须包含有效的 options。")
    if options.schema_version != 1:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "不支持此版本的模型请求选项。")
    if type(options.max_completion_tokens) is not int or not 1 <= options.max_completion_tokens <= MAX_COMPLETION_TOKENS:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "max_completion_tokens 超出允许范围。")
    if type(options.stream) is not bool:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "stream 必须是布尔值。")
    if options.thinking_mode is not None and type(options.thinking_mode) is not bool:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "thinking_mode 必须是布尔值。")
    if options.reasoning_effort is not None and not isinstance(options.reasoning_effort, str):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "reasoning_effort 必须是字符串。")
    if len(request.instructions) > MAX_INSTRUCTION_COUNT:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "指令块数量超出允许范围。")
    if len(request.messages) > MAX_MESSAGE_COUNT:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "对话消息数量超出允许范围。")
    if len(request.tools) > MAX_TOOL_COUNT:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具定义数量超出允许范围。")

    text_bytes = 0
    image_count = 0
    image_bytes = 0
    for instruction in request.instructions:
        if not isinstance(instruction, InstructionBlock) or not isinstance(instruction.role, InstructionRole):
            raise fail(ProviderFailureCode.INVALID_REQUEST, "指令角色或结构无效。")
        if not isinstance(instruction.content, str):
            raise fail(ProviderFailureCode.INVALID_REQUEST, "指令内容必须是文本。")
        text_bytes += len(instruction.content.encode("utf-8"))

    pending_tool_calls: set[str] = set()
    seen_tool_call_ids: set[str] = set()
    for message in request.messages:
        if not isinstance(message, ProviderMessage) or not isinstance(message.role, MessageRole):
            raise fail(ProviderFailureCode.INVALID_REQUEST, "对话消息角色或结构无效。")
        blocks = _content_blocks(message.content)
        for block in blocks:
            if isinstance(block, TextBlock):
                if not isinstance(block.text, str):
                    raise fail(ProviderFailureCode.INVALID_REQUEST, "文本内容必须是字符串。")
                text_bytes += len(block.text.encode("utf-8"))
            elif isinstance(block, ImageBlock):
                if message.role is not MessageRole.USER:
                    raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "图片仅支持出现在 user 消息中。")
                if not isinstance(block.media_type, str) or block.media_type not in SUPPORTED_MEDIA_TYPES:
                    raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "不支持此图片格式。")
                if not isinstance(block.image_bytes, bytes) or not block.image_bytes:
                    raise fail(ProviderFailureCode.INVALID_REQUEST, "图片内容不能为空。")
                if len(block.image_bytes) > MAX_IMAGE_BYTES:
                    raise fail(ProviderFailureCode.INVALID_REQUEST, "单张图片超出允许大小。")
                image_count += 1
                image_bytes += len(block.image_bytes)
            else:
                raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "不支持此消息内容类型。")

        if message.role is MessageRole.TOOL:
            if message.tool_call_id is None or message.tool_call_id not in pending_tool_calls:
                raise fail(ProviderFailureCode.INVALID_REQUEST, "工具结果未关联到之前的工具调用。")
            pending_tool_calls.remove(message.tool_call_id)
            if message.tool_calls or message.continuation is not None:
                raise fail(ProviderFailureCode.INVALID_REQUEST, "tool 消息不能包含工具调用或续接数据。")
        else:
            if message.tool_call_id is not None:
                raise fail(ProviderFailureCode.INVALID_REQUEST, "仅 tool 消息可以设置 tool_call_id。")
            if message.role is MessageRole.USER and (message.tool_calls or message.continuation is not None):
                raise fail(ProviderFailureCode.INVALID_REQUEST, "user 消息不能包含工具调用或续接数据。")
            if message.role is MessageRole.ASSISTANT:
                if len(message.tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
                    raise fail(ProviderFailureCode.INVALID_REQUEST, "单条消息的工具调用数量超出允许范围。")
                for call in message.tool_calls:
                    _validate_tool_call(call)
                    text_bytes += len(call.arguments.encode("utf-8"))
                    if call.call_id in seen_tool_call_ids:
                        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具调用 ID 重复。")
                    seen_tool_call_ids.add(call.call_id)
                    pending_tool_calls.add(call.call_id)
                if message.continuation is not None:
                    _validate_continuation(message.continuation, provider_id)
                    text_bytes += len(message.continuation.reasoning_content.encode("utf-8"))
        if message.role is not MessageRole.USER and any(isinstance(block, ImageBlock) for block in blocks):
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "图片仅支持出现在 user 消息中。")

    if pending_tool_calls:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "历史工具调用缺少对应的工具结果。")
    if image_count > MAX_IMAGE_COUNT or image_bytes > MAX_TOTAL_IMAGE_BYTES:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "图片总量超出允许范围。")

    for tool in request.tools:
        _validate_function_tool(tool, provider_id)
        text_bytes += len(tool.description.encode("utf-8"))
        try:
            text_bytes += len(canonical_json_dumps(tool.parameters).encode("utf-8"))
        except JsonValueError:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "工具 Schema 必须是合法 JSON 数据。") from None
    if text_bytes > MAX_TOTAL_TEXT_BYTES:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "请求文本和工具 Schema 总量超出允许范围。")


def _content_blocks(content: object) -> tuple[TextBlock | ImageBlock, ...]:
    if isinstance(content, str):
        return (TextBlock(content),)
    if isinstance(content, tuple):
        if all(isinstance(block, (TextBlock, ImageBlock)) for block in content):
            return content
    raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "不支持此消息内容类型。")


def _validate_tool_call(call: object) -> None:
    if not isinstance(call, ProviderToolCall):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具调用结构无效。")
    if (
        not isinstance(call.call_id, str)
        or not call.call_id
        or len(call.call_id) > 256
        or not isinstance(call.name, str)
        or not _TOOL_NAME.fullmatch(call.name)
    ):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具调用名称或 ID 无效。")
    if not isinstance(call.arguments, str):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具调用参数必须是 JSON 字符串。")


def _validate_continuation(value: ProviderContinuation, expected: ProviderId) -> None:
    if value.provider_id is not expected or value.format_version != 1:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "续接数据与当前服务商或格式版本不匹配。")
    if not isinstance(value.reasoning_content, str):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "续接数据格式无效。")


def _validate_function_tool(tool: object, provider_id: ProviderId) -> None:
    if not isinstance(tool, FunctionTool):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "函数工具结构无效。")
    if not isinstance(tool.name, str) or not _TOOL_NAME.fullmatch(tool.name):
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具名称必须为 1 到 64 个字母、数字、下划线或短横线。")
    if not isinstance(tool.description, str) or len(tool.description) > 8192:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "工具描述无效或超出允许范围。")
    if tool.strict is not None and type(tool.strict) is not bool:
        raise fail(ProviderFailureCode.INVALID_REQUEST, "strict 必须是布尔值。")
    try:
        schema = validate_schema_definition(tool.parameters, require_object=True)
    except SchemaDefinitionError as error:
        failure_code, safe_message = _provider_schema_error(error)
        raise fail(failure_code, safe_message) from None

    if tool.strict is True:
        if provider_id is ProviderId.QWEN:
            raise fail(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "qwen3.8-flash 的 function strict 模式尚无受支持的 Chat Completions 合同。",
            )
        if provider_id is ProviderId.DEEPSEEK:
            # DeepSeek documents strict tool calls on its beta base URL and
            # requires every function in the request to use strict mode.
            # Endpoint-aware checks for the full list happen in the adapter.
            _validate_strict_schema(schema, depth=0)
        if provider_id is ProviderId.MIMO:
            _validate_strict_schema(schema, depth=0)


def validate_tools_for_endpoint(
    tools: Iterable[FunctionTool], provider_id: ProviderId, base_url: str
) -> None:
    tool_list = tuple(tools)
    strict = [tool.strict is True for tool in tool_list]
    if provider_id is ProviderId.DEEPSEEK and any(strict):
        path = urlsplit(base_url).path.rstrip("/")
        if not path.endswith("/beta"):
            raise fail(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "DeepSeek strict function calling 需要将 FIGURA_DEEPSEEK_BASE_URL 配置为 Beta 接口。",
            )
        if not all(strict):
            raise fail(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "DeepSeek strict 模式要求本次请求中的所有函数都启用 strict。",
            )


def _provider_schema_error(error: SchemaDefinitionError) -> tuple[ProviderFailureCode, str]:
    messages = {
        "top_level_not_object": "函数参数 Schema 顶层必须是 object。",
        "unsupported_keyword": "工具 Schema 包含当前适配器不支持的关键字。",
        "unsupported_type": "工具 Schema 使用了不支持的数据类型。",
        "schema_too_deep": "工具 Schema 嵌套层级超出允许范围。",
        "schema_too_large": "工具 Schema 超出允许大小。",
        "schema_not_object": "函数参数 Schema 顶层必须是 object。",
        "schema_not_json": "工具 Schema 必须是合法 JSON 数据。",
        "invalid_properties": "工具 Schema 的 properties 结构无效。",
        "invalid_required": "工具 Schema 的 required 必须是字符串数组。",
        "invalid_required_reference": "工具 Schema 的 required 引用了无效字段。",
        "invalid_items": "当前适配器不支持此 items Schema。",
        "invalid_additional_properties": "additionalProperties 必须是布尔值或 Schema。",
        "invalid_enum": "工具 Schema 的 enum 必须包含 1 到 256 个值。",
        "invalid_anyOf": "工具 Schema 的 anyOf 结构无效。",
        "invalid_description": "工具 Schema 的 description 必须是有界字符串。",
        "invalid_title": "工具 Schema 的 title 必须是有界字符串。",
        "invalid_pattern": "工具 Schema 的 pattern 必须是有界有效正则表达式。",
        "invalid_minimum": "工具 Schema 的 minimum 必须是有限数值。",
        "invalid_maximum": "工具 Schema 的 maximum 必须是有限数值。",
        "invalid_exclusiveMinimum": "工具 Schema 的 exclusiveMinimum 必须是有限数值。",
        "invalid_exclusiveMaximum": "工具 Schema 的 exclusiveMaximum 必须是有限数值。",
        "invalid_minLength": "工具 Schema 的 minLength 必须是非负整数。",
        "invalid_maxLength": "工具 Schema 的 maxLength 必须是非负整数。",
        "invalid_minItems": "工具 Schema 的 minItems 必须是非负整数。",
        "invalid_maxItems": "工具 Schema 的 maxItems 必须是非负整数。",
        "invalid_uniqueItems": "工具 Schema 的 uniqueItems 必须是布尔值。",
    }
    unsupported = error.code in {"unsupported_keyword", "unsupported_type", "invalid_items"}
    code = ProviderFailureCode.UNSUPPORTED_CAPABILITY if unsupported else ProviderFailureCode.INVALID_REQUEST
    return code, messages.get(error.code, "工具 Schema 结构无效。")


def _validate_strict_schema(schema: Mapping[str, Any], depth: int) -> None:
    if schema.get("type") == "object":
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is not False:
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "strict object Schema 必须设置 additionalProperties=false。")
        if set(schema.get("required", [])) != set(properties):
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "strict object Schema 要求 properties 中的字段全部 required。")
        for nested in properties.values():
            _validate_strict_schema(nested, depth + 1)
    elif schema.get("type") == "array":
        items = schema.get("items")
        if not isinstance(items, Mapping):
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "strict array Schema 必须声明 items。")
        _validate_strict_schema(items, depth + 1)
    if "anyOf" in schema:
        for nested in schema["anyOf"]:
            _validate_strict_schema(nested, depth + 1)
