"""Projection from durable Figura conversation facts to a bounded Provider request."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from dataclasses import replace
from types import MappingProxyType
from figura.shared.payloads import encode_json

from figura.agent.context_compaction import CompactionSelection
from figura.agent.execution_images import RunExecutionImageReader
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.execution_resources import (
    ImageResourceRef,
    PanelContent,
    RunExecutionState,
    ToolResourceRef,
)
from figura.agent.prompting.execution import build_context_summary_instruction, build_execution_instruction
from figura.agent.prompting.loader import PromptAssetError, build_compaction_instruction
from figura.agent.prompting.loader import build_static_instruction
from figura.agent.prompting.observations import build_observation_messages
from figura.agent.prompting.tools import build_tool_instruction
from figura.memory import (
    AssistantMessage,
    MemoryMessage,
    ToolMessage,
    UserMessage,
    project_run_messages,
    project_session_history,
)
from figura.providers import (
    MessageRole,
    ProviderContinuation,
    ProviderId,
    ProviderMessage,
    ProviderOptions,
    ProviderRequest,
    ProviderToolCall,
)
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import ActionKind, RecordKind, RunStatus, ToolFactKind
from figura.runtime.records import RunInput, RunState, SessionContextCheckpoint, ToolCallFact
from figura.shared.source_refs import HistorySourceRef, MessageSourceRef, ToolResultSourceRef
from figura.tools import ToolRegistry, project_provider_tools


class AgentRequestBuilder:
    """Build one validated model request from Session history and the current Run."""

    __slots__ = ("_execution_state", "_execution_images")

    def __init__(
        self,
        execution_state: RunExecutionStateService,
        execution_images: RunExecutionImageReader,
    ) -> None:
        if not isinstance(execution_state, RunExecutionStateService):
            raise TypeError("execution_state must be a RunExecutionStateService")
        if not isinstance(execution_images, RunExecutionImageReader):
            raise TypeError("execution_images must be a RunExecutionImageReader")
        object.__setattr__(self, "_execution_state", execution_state)
        object.__setattr__(self, "_execution_images", execution_images)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("AgentRequestBuilder is immutable")

    def build(
        self,
        state: RunState,
        registry: ToolRegistry,
        prior_run_states: tuple[RunState, ...] = (),
        *,
        context_checkpoint: SessionContextCheckpoint | None = None,
    ) -> ProviderRequest:
        if not isinstance(state, RunState) or not isinstance(registry, ToolRegistry):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if (
            state.run.status is not RunStatus.RUNNING
            or state.checkpoint.next_action is None
            or state.checkpoint.next_action.action_kind not in {ActionKind.MODEL, ActionKind.PROVIDER_RETRY}
        ):
            raise RunError(RunErrorCode.INVALID_TRANSITION)
        try:
            provider_id = ProviderId(state.run.provider)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        history = project_session_history(state.run, prior_run_states)
        if context_checkpoint is not None:
            if (
                not isinstance(context_checkpoint, SessionContextCheckpoint)
                or context_checkpoint.session_id != state.run.session_id
                or context_checkpoint.covered_run_ordinal >= state.run.ordinal
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            history = replace(
                history,
                messages=tuple(
                    item for item in history.messages
                    if _message_is_after_checkpoint(item, prior_run_states, context_checkpoint)
                ),
                run_outcomes=tuple(
                    item for item in history.run_outcomes
                    if _run_outcome_is_after_checkpoint(item, prior_run_states, context_checkpoint)
                ),
            )
        historical_inputs = _historical_input_entries(prior_run_states)
        full_execution_state = self._execution_state.build(state, prior_run_states)
        execution_state = _prompt_resource_projection(
            full_execution_state, state, prior_run_states, context_checkpoint
        )
        messages = self._provider_messages(
            (*history.messages, *project_run_messages(state)),
            selected_provider=provider_id,
            continuations=_continuations_by_response((*prior_run_states, state)),
            registry=registry,
            historical_inputs=historical_inputs,
        )
        if historical_inputs:
            messages = (
                _historical_user_inputs_message(historical_inputs),
                *messages,
            )
        messages = (
            *messages,
            *build_observation_messages(state, execution_state, self._execution_images),
        )
        try:
            tools = project_provider_tools(registry)
        except (TypeError, ValueError):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD) from None

        instructions = (
            build_static_instruction(),
            build_tool_instruction(registry),
            *((build_context_summary_instruction(context_checkpoint),) if context_checkpoint else ()),
            build_execution_instruction(execution_state, history.run_outcomes),
        )
        registry_projection = [{"name": d.name, "description": d.description,
            "parameters": d.parameters_schema, "result": d.result_schema,
            "replay_effect": d.replay_effect.value} for d in registry]
        asset_contract = MappingProxyType({
            "prompt_digest": hashlib.sha256(encode_json([
                {"role": i.role.value, "content": i.content} for i in instructions]).encode()).hexdigest(),
            "registry_version": registry.version,
            "registry_digest": hashlib.sha256(encode_json(registry_projection).encode()).hexdigest(),
        })
        request = ProviderRequest(
            provider_id=provider_id,
            model_id=state.run.model,
            instructions=instructions,
            messages=messages,
            options=ProviderOptions(
                stream=False,
            ),
            tools=tools,
            asset_contract=asset_contract,
        )
        return request

    def build_summary_request(
        self,
        state: RunState,
        selected_run_states: tuple[RunState, ...],
        previous_checkpoint: SessionContextCheckpoint | None,
        *,
        coverage: CompactionSelection | None = None,
        context_capacity_tokens: int,
        summary_budget_tokens: int,
    ) -> tuple[ProviderRequest, tuple[HistorySourceRef, ...]]:
        """Build a tool-free request over a stable, complete source slice."""
        if (
            not isinstance(state, RunState)
            or not isinstance(selected_run_states, tuple)
            or not selected_run_states
            or any(not isinstance(item, RunState) for item in selected_run_states)
            or type(context_capacity_tokens) is not int
            or context_capacity_tokens <= 0
            or type(summary_budget_tokens) is not int
            or summary_budget_tokens != context_capacity_tokens // 10
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if previous_checkpoint is not None and (
            previous_checkpoint.session_id != state.run.session_id
            or previous_checkpoint.covered_run_ordinal > selected_run_states[-1].run.ordinal
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if coverage is not None and (
            coverage.covered_run_ordinal < selected_run_states[0].run.ordinal
            or coverage.covered_run_ordinal > selected_run_states[-1].run.ordinal
            or selected_run_states[-1].run.run_id != coverage.covered_run_id
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)

        refs: list[HistorySourceRef] = list(
            previous_checkpoint.source_refs if previous_checkpoint else ()
        )
        source_runs: list[dict[str, object]] = []
        for source_state in selected_run_states:
            if (
                source_state.run.session_id != state.run.session_id
                or source_state.run.status is not RunStatus.COMPLETED
            ):
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
            run_messages = project_run_messages(source_state)
            input_messages = tuple(item for item in run_messages if isinstance(item, UserMessage))
            if len(input_messages) != 1:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            source_input = input_messages[0]
            input_ref = MessageSourceRef(source_input.run_id, source_input.source_record_id)
            if (
                source_input.run_id != source_state.run.run_id
                or source_input.run_ordinal != source_state.run.ordinal
                or source_input.source_record_id != source_state.run.input_record_id
            ):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            refs.append(input_ref)
            projected_messages: list[dict[str, object]] = []
            source_messages = tuple(
                message for message in run_messages
                if _message_is_within_compaction_slice(
                    message, source_state, previous_checkpoint, coverage
                )
                and not isinstance(message, UserMessage)
            )
            if not source_messages:
                continue
            for message in source_messages:
                if isinstance(message, UserMessage):
                    ref = MessageSourceRef(message.run_id, message.source_record_id)
                    projected_messages.append({
                        "reference": ref.to_dict(),
                        "role": "user",
                        "text": message.text,
                        "attachment_ids": list(message.attachment_ids),
                    })
                elif isinstance(message, AssistantMessage):
                    ref = MessageSourceRef(message.run_id, message.source_record_id)
                    projected_messages.append({
                        "reference": ref.to_dict(),
                        "role": "assistant",
                        "text": message.content,
                        "tool_calls": [
                            {
                                "call_id": call.call_id,
                                "tool_name": call.tool_name,
                                "arguments": call.arguments_json,
                            }
                            for call in message.tool_calls
                        ],
                    })
                elif isinstance(message, ToolMessage):
                    ref = ToolResultSourceRef(message.run_id, message.tool_call_id)
                    projected_messages.append({
                        "reference": ref.to_dict(),
                        "role": "tool",
                        "tool_call_id": message.tool_call_id,
                        "content": message.content,
                    })
                else:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                refs.append(ref)
            source_runs.append({
                "run_id": source_state.run.run_id,
                "run_ordinal": source_state.run.ordinal,
                "status": source_state.run.status.value,
                "terminal_code": source_state.run.terminal_code,
                "input": {
                    "reference": input_ref.to_dict(),
                    "text": source_input.text,
                    "attachment_ids": list(source_input.attachment_ids),
                },
                "messages": projected_messages,
            })

        unique_refs = tuple(dict.fromkeys(refs))
        source_payload = {
            "previous_summary": (
                None if previous_checkpoint is None
                else json.loads(encode_json(previous_checkpoint.summary))
            ),
            "previous_source_refs": [
                ref.to_dict() for ref in (
                    previous_checkpoint.source_refs if previous_checkpoint else ()
                )
            ],
            "source_runs": source_runs,
        }
        try:
            instructions = (build_compaction_instruction(
                context_capacity_tokens=context_capacity_tokens,
                summary_budget_tokens=summary_budget_tokens,
            ),)
        except PromptAssetError:
            raise ValueError("summary prompt asset cannot be loaded") from None
        tools: tuple = ()
        instruction_projection = [
            {"role": item.role.value, "content": item.content} for item in instructions
        ]
        asset_contract = MappingProxyType({
            "prompt_digest": hashlib.sha256(encode_json(instruction_projection).encode()).hexdigest(),
            "registry_version": "context-compaction-v2",
            "registry_digest": hashlib.sha256(encode_json(tools).encode()).hexdigest(),
        })
        request = ProviderRequest(
            provider_id=state.run.provider,
            model_id=state.run.model,
            instructions=instructions,
            messages=(ProviderMessage(
                MessageRole.USER,
                json.dumps(source_payload, ensure_ascii=False, separators=(",", ":")),
            ),),
            options=ProviderOptions(stream=False),
            tools=tools,
            asset_contract=asset_contract,
        )
        return request, unique_refs

    def _provider_messages(
        self,
        messages: tuple[MemoryMessage, ...],
        *,
        selected_provider: ProviderId,
        continuations: dict[tuple[str, str], ProviderContinuation],
        registry: ToolRegistry,
        historical_inputs: dict[str, dict[str, object]],
    ) -> tuple[ProviderMessage, ...]:
        projected: list[ProviderMessage] = []
        resolved_calls_by_response: dict[tuple[str, str], set[str]] = {}
        for index, message in enumerate(messages):
            if not isinstance(message, AssistantMessage):
                continue
            key = (message.run_id, message.source_record_id)
            paired = set()
            for following in messages[index + 1 :]:
                if not isinstance(following, ToolMessage):
                    break
                paired.add(following.tool_call_id)
            resolved_calls_by_response[key] = paired
        last_historical_run_id: str | None = None
        for message in messages:
            if isinstance(message, UserMessage):
                if message.run_id in historical_inputs:
                    continue
                projected.append(
                    ProviderMessage(
                        MessageRole.USER,
                        _user_text(message.text, message.attachment_ids),
                    )
                )
            elif isinstance(message, AssistantMessage):
                historical_input = historical_inputs.get(message.run_id)
                if historical_input is not None and last_historical_run_id != message.run_id:
                    projected.append(_historical_run_context_message(historical_input))
                    last_historical_run_id = message.run_id
                paired_calls = resolved_calls_by_response.get(
                    (message.run_id, message.source_record_id), set()
                )
                if any(
                    call.registry_version != registry.version and call.call_id not in paired_calls
                    for call in message.tool_calls
                ):
                    raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
                continuation = continuations.get(
                    (message.run_id, message.source_record_id)
                )
                if continuation is not None and continuation.provider_id is not selected_provider:
                    continuation = None
                projected.append(
                    ProviderMessage(
                        role=MessageRole.ASSISTANT,
                        content=message.content,
                        tool_calls=tuple(
                            ProviderToolCall(
                                call_id=call.call_id,
                                name=call.tool_name,
                                arguments=call.arguments_json,
                            )
                            for call in message.tool_calls
                        ),
                        continuation=continuation,
                    )
                )
            elif isinstance(message, ToolMessage):
                historical_input = historical_inputs.get(message.run_id)
                if historical_input is not None and last_historical_run_id != message.run_id:
                    projected.append(_historical_run_context_message(historical_input))
                    last_historical_run_id = message.run_id
                projected.append(
                    ProviderMessage(
                        role=MessageRole.TOOL,
                        content=message.content,
                        tool_call_id=message.tool_call_id,
                    )
                )
            else:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return tuple(projected)


def _historical_input_entries(
    prior_run_states: tuple[RunState, ...],
) -> dict[str, dict[str, object]]:
    entries: dict[str, dict[str, object]] = {}
    for state in prior_run_states:
        input_records = tuple(
            record for record in state.records
            if record.record_id == state.run.input_record_id
        )
        if len(input_records) != 1:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        input_record = input_records[0]
        source = input_record.payload
        if (
            input_record is not state.records[0]
            or input_record.run_id != state.run.run_id
            or input_record.record_sequence != 1
            or input_record.record_kind is not RecordKind.INPUT
            or not isinstance(source, RunInput)
            or not isinstance(source.text, str)
            or not isinstance(source.attachment_ids, tuple)
            or any(not isinstance(item, str) for item in source.attachment_ids)
            or state.run.run_id in entries
        ):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        reference = MessageSourceRef(state.run.run_id, input_record.record_id)
        entries[state.run.run_id] = {
            "run_id": state.run.run_id,
            "run_ordinal": state.run.ordinal,
            "text": source.text,
            "attachment_ids": list(source.attachment_ids),
            "source_ref": reference.to_dict(),
        }
    return entries


def _historical_user_inputs_message(
    entries: Mapping[str, Mapping[str, object]],
) -> ProviderMessage:
    content = json.dumps(
        {
            "figura_context_type": "historical_user_inputs",
            "entries": list(entries.values()),
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return ProviderMessage(MessageRole.USER, content)


def _historical_run_context_message(
    entry: Mapping[str, object],
) -> ProviderMessage:
    content = json.dumps(
        {
            "figura_context_type": "historical_run_context",
            "run_id": entry["run_id"],
            "run_ordinal": entry["run_ordinal"],
            "input_ref": entry["source_ref"],
        },
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return ProviderMessage(MessageRole.USER, content)


def _continuations_by_response(
    states: tuple[RunState, ...],
) -> dict[tuple[str, str], ProviderContinuation]:
    result: dict[tuple[str, str], ProviderContinuation] = {}
    for state in states:
        if not isinstance(state, RunState):
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        for fact in state.provider_continuations:
            key = (fact.run_id, fact.response_record_id)
            if fact.run_id != state.run.run_id or key in result:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            try:
                result[key] = ProviderContinuation(
                    provider_id=ProviderId(fact.provider_id),
                    format_version=fact.format_version,
                    reasoning_content=fact.reasoning_content,
                )
            except (TypeError, ValueError):
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
    return result


def _user_text(text: str, attachment_ids: tuple[str, ...]) -> str:
    if not attachment_ids:
        return text
    return f"{text}\n\n本条消息附件 ID：{', '.join(attachment_ids)}"


def _prompt_resource_projection(
    state: RunExecutionState,
    current: RunState,
    prior: tuple[RunState, ...],
    checkpoint: SessionContextCheckpoint | None,
) -> RunExecutionState:
    if checkpoint is None:
        return state
    relevant_run_ids = {
        run_state.run.run_id
        for run_state in prior
        if run_state.run.ordinal > checkpoint.covered_run_ordinal
    }
    relevant_run_ids.add(current.run.run_id)
    relevant_image_ids: set[str] = set()
    relevant_tool_refs: set[tuple[str, str]] = set()
    by_run_id = {run_state.run.run_id: run_state for run_state in (*prior, current)}
    for run_state in (*prior, current):
        if run_state.run.ordinal > checkpoint.covered_run_ordinal:
            relevant_image_ids.update(_run_input_attachment_ids(run_state))
    for ref in checkpoint.source_refs:
        if isinstance(ref, MessageSourceRef):
            source_state = by_run_id.get(ref.run_id)
            if source_state is None:
                continue
            if ref.record_id == source_state.run.input_record_id:
                relevant_image_ids.update(_run_input_attachment_ids(source_state))
            else:
                for fact in source_state.tool_facts:
                    if (
                        isinstance(fact.payload, ToolCallFact)
                        and fact.payload.response_record_id == ref.record_id
                    ):
                        relevant_tool_refs.add((source_state.run.run_id, fact.payload.call_id))
        elif isinstance(ref, ToolResultSourceRef):
            relevant_tool_refs.add((ref.run_id, ref.call_id))

    for run_state in (*prior, current):
        record_sequences = {item.record_id: item.record_sequence for item in run_state.records}
        for fact in run_state.tool_facts:
            if fact.fact_kind is not ToolFactKind.TOOL_CALL or not isinstance(
                fact.payload, ToolCallFact
            ):
                continue
            response_sequence = record_sequences.get(fact.payload.response_record_id)
            if response_sequence is None:
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            is_raw = run_state.run.ordinal > checkpoint.covered_run_ordinal or (
                run_state.run.ordinal == checkpoint.covered_run_ordinal
                and response_sequence > checkpoint.covered_record_sequence
            )
            if not is_raw:
                continue
            relevant_tool_refs.add((run_state.run.run_id, fact.payload.call_id))
            try:
                arguments = json.loads(fact.payload.arguments_json)
            except (TypeError, ValueError):
                raise RunError(RunErrorCode.INTEGRITY_ERROR) from None
            if not isinstance(arguments, dict):
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            raw_ref = arguments.get("resource_ref")
            if isinstance(raw_ref, dict):
                _include_resource_reference(raw_ref, relevant_image_ids, relevant_tool_refs)
            source_kind, source_id = arguments.get("source_kind"), arguments.get("source_id")
            if source_kind in {"attachment", "panel"} and isinstance(source_id, str):
                relevant_image_ids.add(source_id)

    resources = []
    for resource in state.resources:
        ref = resource.ref
        content = resource.content
        if isinstance(content, PanelContent):
            include = (
                content.run_id in relevant_run_ids
                or ref.id in relevant_image_ids
                or content.source_attachment_id in relevant_image_ids
            )
        elif isinstance(ref, ImageResourceRef):
            include = ref.id in relevant_image_ids
        elif isinstance(ref, ToolResourceRef):
            include = (
                (ref.run_id in relevant_run_ids and ref.run_id != checkpoint.covered_run_id)
                or (ref.run_id, ref.call_id) in relevant_tool_refs
            )
        else:
            include = False
        if include:
            resources.append(resource)
    return RunExecutionState(state.run_id, tuple(resources))


def _include_resource_reference(
    value: dict[str, object],
    image_ids: set[str],
    tool_refs: set[tuple[str, str]],
) -> None:
    kind = value.get("kind")
    if kind in {"attachment", "panel"} and isinstance(value.get("id"), str):
        image_ids.add(value["id"])
    elif (
        kind in {"ocr", "measurement", "chart_figure", "chart_render"}
        and isinstance(value.get("run_id"), str)
        and isinstance(value.get("call_id"), str)
    ):
        tool_refs.add((value["run_id"], value["call_id"]))


def _run_input_attachment_ids(state: RunState) -> tuple[str, ...]:
    record = next(
        (item for item in state.records if item.record_id == state.run.input_record_id),
        None,
    )
    if record is None or not isinstance(record.payload, RunInput):
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return tuple(record.payload.attachment_ids)


def _message_is_after_checkpoint(
    message: MemoryMessage,
    prior: tuple[RunState, ...],
    checkpoint: SessionContextCheckpoint,
) -> bool:
    if message.run_ordinal > checkpoint.covered_run_ordinal:
        return True
    if message.run_ordinal < checkpoint.covered_run_ordinal:
        return False
    state = next((item for item in prior if item.run.run_id == message.run_id), None)
    if state is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    if isinstance(message, ToolMessage):
        return message.source_tool_sequence > checkpoint.covered_tool_sequence
    sequence = next(
        (item.record_sequence for item in state.records
         if item.record_id == message.source_record_id),
        None,
    )
    if sequence is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return sequence > checkpoint.covered_record_sequence


def _run_outcome_is_after_checkpoint(
    outcome,
    prior: tuple[RunState, ...],
    checkpoint: SessionContextCheckpoint,
) -> bool:
    if outcome.run_ordinal > checkpoint.covered_run_ordinal:
        return True
    if outcome.run_ordinal < checkpoint.covered_run_ordinal:
        return False
    state = next((item for item in prior if item.run.run_id == outcome.run_id), None)
    if state is None:
        return True
    return any(
        record.record_sequence > checkpoint.covered_record_sequence
        and record.record_kind.value != "final_answer"
        for record in state.records
    ) or any(
        fact.tool_sequence > checkpoint.covered_tool_sequence
        for fact in state.tool_facts
    )


def _message_is_within_compaction_slice(
    message: MemoryMessage,
    state: RunState,
    previous_checkpoint: SessionContextCheckpoint | None,
    coverage: CompactionSelection | None,
) -> bool:
    if previous_checkpoint is not None:
        if state.run.ordinal < previous_checkpoint.covered_run_ordinal:
            return False
        if state.run.ordinal == previous_checkpoint.covered_run_ordinal:
            if isinstance(message, ToolMessage):
                if message.source_tool_sequence <= previous_checkpoint.covered_tool_sequence:
                    return False
            else:
                record_sequence = next(
                    (item.record_sequence for item in state.records
                     if item.record_id == message.source_record_id),
                    None,
                )
                if record_sequence is None:
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if record_sequence <= previous_checkpoint.covered_record_sequence:
                    return False
    if coverage is None or state.run.ordinal < coverage.covered_run_ordinal:
        return True
    if state.run.ordinal > coverage.covered_run_ordinal:
        return False
    if state.run.run_id != coverage.covered_run_id:
        return False
    if isinstance(message, ToolMessage):
        return message.source_tool_sequence <= coverage.covered_tool_sequence
    record_sequence = next(
        (item.record_sequence for item in state.records
         if item.record_id == message.source_record_id),
        None,
    )
    if record_sequence is None:
        raise RunError(RunErrorCode.INTEGRITY_ERROR)
    return record_sequence <= coverage.covered_record_sequence
