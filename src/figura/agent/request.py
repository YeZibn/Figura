"""Pure projection from committed Run facts to a bounded Provider request."""

from __future__ import annotations

from pathlib import Path

from figura.attachments import FiguraAttachmentService
from figura.json_schema import JsonValueError, canonical_json_dumps
from figura.providers import (
    FinishReason,
    ImageBlock,
    InstructionBlock,
    InstructionRole,
    MessageRole,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderToolCall,
    TextBlock,
)
from figura.providers.errors import ProviderCallError
from figura.providers.validation import (
    MAX_INSTRUCTION_COUNT,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_COUNT,
    MAX_MESSAGE_COUNT,
    MAX_TOTAL_IMAGE_BYTES,
    MAX_TOTAL_TEXT_BYTES,
    MAX_TOOL_COUNT,
    validate_request,
)
from figura.runtime import RunError, RunErrorCode
from figura.runtime.domain.models import (
    ActionKind,
    ExecutionRecord,
    ModelResponseFact,
    ProviderContinuationFact,
    RecordKind,
    RunState,
    RunStatus,
    RunInput,
    ToolCallFact,
    ToolExecutionFact,
    ToolFactKind,
    ToolResultFact,
)
from figura.tools import ToolRegistry, project_provider_tools


_SYSTEM_INSTRUCTION = Path(__file__).with_name("assets").joinpath("system-v1.md").read_text(
    encoding="utf-8"
)
_MAX_COMPLETION_TOKENS = 4096


class AgentRequestBuilder:
    """Build one validated model request from the current durable Run state."""

    __slots__ = ("_attachments",)

    def __init__(self, attachments: FiguraAttachmentService | None = None) -> None:
        if attachments is not None and not isinstance(attachments, FiguraAttachmentService):
            raise TypeError("attachments must be a FiguraAttachmentService")
        object.__setattr__(self, "_attachments", attachments)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AgentRequestBuilder is immutable")

    def build(self, state: RunState, registry: ToolRegistry) -> ProviderRequest:
        if not isinstance(state, RunState) or not isinstance(registry, ToolRegistry):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if (
            state.run.status is not RunStatus.RUNNING
            or state.checkpoint.next_action is None
            or state.checkpoint.next_action.action_kind is not ActionKind.MODEL
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        try:
            provider_id = ProviderId(state.run.provider)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        input_records = [record for record in state.records if record.record_kind is RecordKind.INPUT]
        if len(input_records) != 1 or input_records[0].record_id != state.run.input_record_id:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        run_input = input_records[0].payload
        if not isinstance(run_input, RunInput):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)

        instructions = (InstructionBlock(InstructionRole.SYSTEM, _SYSTEM_INSTRUCTION),)
        tools = self._project_tools(registry)
        rounds = self._project_rounds(state, registry)
        user_message = ProviderMessage(
            MessageRole.USER,
            self._user_content(state.run.session_id, run_input.text, run_input.attachment_ids),
        )
        retained_rounds = list(rounds)

        while True:
            messages = (user_message,) + tuple(
                message for round_messages in retained_rounds for message in round_messages
            )
            request = ProviderRequest(
                provider_id=provider_id,
                model_id=state.run.model,
                instructions=instructions,
                messages=messages,
                options=ProviderOptions(
                    max_completion_tokens=_MAX_COMPLETION_TOKENS,
                    stream=False,
                ),
                tools=tools,
            )
            if _within_provider_limits(request):
                break
            if len(retained_rounds) <= 1:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            retained_rounds.pop(0)

        try:
            validate_request(request, provider_id)
        except ProviderCallError:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None
        return request

    def _user_content(
        self,
        session_id: str,
        text: str,
        attachment_ids: tuple[str, ...],
    ) -> str | tuple[TextBlock | ImageBlock, ...]:
        if not attachment_ids:
            return text
        if len(attachment_ids) > MAX_IMAGE_COUNT or self._attachments is None:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        images: list[ImageBlock] = []
        total_image_bytes = 0
        for attachment_id in attachment_ids:
            image = self._attachments.resolve(session_id, attachment_id)
            if (
                not isinstance(image, ImageBlock)
                or not isinstance(image.image_bytes, bytes)
                or not image.image_bytes
                or len(image.image_bytes) > MAX_IMAGE_BYTES
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            total_image_bytes += len(image.image_bytes)
            if total_image_bytes > MAX_TOTAL_IMAGE_BYTES:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            images.append(image)
        return (TextBlock(text), *images)

    @staticmethod
    def _project_tools(registry: ToolRegistry):
        try:
            return project_provider_tools(registry)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

    @staticmethod
    def _project_rounds(
        state: RunState,
        registry: ToolRegistry,
    ) -> tuple[tuple[ProviderMessage, ...], ...]:
        calls_by_response: dict[str, list[tuple[ToolExecutionFact, ToolCallFact]]] = {}
        calls_by_sequence: dict[int, tuple[ToolExecutionFact, ToolCallFact]] = {}
        results_by_call: dict[int, list[ToolResultFact]] = {}
        for fact in state.tool_facts:
            if fact.fact_kind is ToolFactKind.TOOL_CALL:
                if not isinstance(fact.payload, ToolCallFact):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                pair = (fact, fact.payload)
                calls_by_response.setdefault(fact.payload.response_record_id, []).append(pair)
                calls_by_sequence[fact.tool_sequence] = pair
            elif fact.fact_kind is ToolFactKind.TOOL_RESULT:
                if not isinstance(fact.payload, ToolResultFact):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                results_by_call.setdefault(fact.payload.tool_call_sequence, []).append(fact.payload)

        continuations = _continuations_by_response(state.provider_continuations, state.run.run_id)
        rounds: list[tuple[ProviderMessage, ...]] = []
        response_ids: set[str] = set()
        for record in state.records:
            if record.record_kind is RecordKind.INPUT:
                continue
            if record.record_kind is not RecordKind.MODEL_RESPONSE or not isinstance(
                record.payload, ModelResponseFact
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            response = record.payload
            if response.finish_reason != FinishReason.TOOL_CALLS.value:
                raise RunError(RunErrorCode.INVALID_TRANSITION)
            response_ids.add(record.record_id)
            call_pairs = sorted(
                calls_by_response.get(record.record_id, ()),
                key=lambda pair: pair[1].position,
            )
            if not call_pairs or [call.position for _, call in call_pairs] != list(
                range(len(call_pairs))
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)

            provider_calls: list[ProviderToolCall] = []
            observations: list[ProviderMessage] = []
            for call_fact, call in call_pairs:
                if call.registry_version != registry.version:
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                results = results_by_call.get(call_fact.tool_sequence, ())
                if len(results) != 1:
                    raise RunError(RunErrorCode.INVALID_TRANSITION)
                result = results[0]
                if result.call_id != call.call_id or result.tool_name != call.tool_name:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                provider_calls.append(
                    ProviderToolCall(
                        call_id=call.call_id,
                        name=call.tool_name,
                        arguments=call.arguments_json,
                    )
                )
                observations.append(
                    ProviderMessage(
                        role=MessageRole.TOOL,
                        content=_tool_observation(result),
                        tool_call_id=call.call_id,
                    )
                )

            continuation_fact = continuations.get(record.record_id)
            continuation = None
            if continuation_fact is not None:
                try:
                    continuation = ProviderContinuation(
                        provider_id=ProviderId(continuation_fact.provider_id),
                        format_version=continuation_fact.format_version,
                        reasoning_content=continuation_fact.reasoning_content,
                    )
                except (TypeError, ValueError):
                    raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
            assistant = ProviderMessage(
                role=MessageRole.ASSISTANT,
                content=response.assistant_content,
                tool_calls=tuple(provider_calls),
                continuation=continuation,
            )
            rounds.append((assistant, *observations))

        if set(calls_by_response) != response_ids:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if set(results_by_call) - set(calls_by_sequence):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if any(sequence not in calls_by_sequence for sequence in results_by_call):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return tuple(rounds)


def _continuations_by_response(
    facts: tuple[ProviderContinuationFact, ...],
    run_id: str,
) -> dict[str, ProviderContinuationFact]:
    result: dict[str, ProviderContinuationFact] = {}
    for fact in facts:
        if fact.run_id != run_id or fact.response_record_id in result:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        result[fact.response_record_id] = fact
    return result


def _tool_observation(result: ToolResultFact) -> str:
    if result.outcome.value == "succeeded":
        if result.error is not None or result.result is None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        payload: dict[str, object] = {
            "outcome": result.outcome.value,
            "result": result.result,
        }
    else:
        if result.error is None or result.result is not None:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        error: dict[str, object] = {
            "code": result.error.code,
            "message": result.error.message,
            "retryable": result.error.retryable,
        }
        if result.error.field_path is not None:
            error["field_path"] = result.error.field_path
        payload = {"outcome": result.outcome.value, "error": error}
    try:
        return canonical_json_dumps(payload)
    except (JsonValueError, TypeError, ValueError):
        raise RunError(RunErrorCode.INTEGRITY_ERROR) from None


def _within_provider_limits(request: ProviderRequest) -> bool:
    if (
        len(request.instructions) > MAX_INSTRUCTION_COUNT
        or len(request.messages) > MAX_MESSAGE_COUNT
        or len(request.tools) > MAX_TOOL_COUNT
    ):
        return False
    text_bytes = sum(len(block.content.encode("utf-8")) for block in request.instructions)
    image_count = 0
    image_bytes = 0
    for message in request.messages:
        content = message.content
        if isinstance(content, str):
            text_bytes += len(content.encode("utf-8"))
        else:
            for block in content:
                if isinstance(block, TextBlock):
                    text_bytes += len(block.text.encode("utf-8"))
                elif isinstance(block, ImageBlock):
                    image_count += 1
                    image_bytes += len(block.image_bytes)
                    if len(block.image_bytes) > MAX_IMAGE_BYTES:
                        return False
                else:
                    return False
        text_bytes += sum(len(call.arguments.encode("utf-8")) for call in message.tool_calls)
        if message.continuation is not None:
            text_bytes += len(message.continuation.reasoning_content.encode("utf-8"))
    for tool in request.tools:
        text_bytes += len(tool.description.encode("utf-8"))
        try:
            text_bytes += len(canonical_json_dumps(tool.parameters).encode("utf-8"))
        except (JsonValueError, TypeError, ValueError):
            return False
    return (
        text_bytes <= MAX_TOTAL_TEXT_BYTES
        and image_count <= MAX_IMAGE_COUNT
        and image_bytes <= MAX_TOTAL_IMAGE_BYTES
    )
