"""Read-only, source-addressable Session history search and retrieval."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import replace

from figura.agent.execution_resources import (
    AttachmentContent,
    ChartFigureContent,
    ChartRenderContent,
    ImageResourceRef,
    MeasurementContent,
    OcrContent,
    PanelContent,
    ResourceRef,
    RunExecutionState,
    ToolResourceRef,
)
from figura.agent.execution_state import RunExecutionStateService
from figura.runtime.coordinator import RunCoordinator
from figura.runtime.errors import RunError, RunErrorCode
from figura.runtime.models import RecordKind, RunStatus, ToolFactKind
from figura.runtime.records import RunState, ToolCallFact, ToolResultFact
from figura.shared.json_schema import canonical_json_dumps
from figura.shared.source_refs import (
    HistorySourceRef,
    MessageSourceRef,
    ToolResultSourceRef,
    source_ref_from_dict,
)
from figura.tools import ToolOutcome

from .models import (
    AssistantMessage,
    MemoryMessage,
    SessionHistory,
    ToolMessage,
    UserMessage,
)
from .projector import project_run_messages, project_session_history, tool_observation


_PAGE_SIZE_DEFAULT = 10
_PAGE_SIZE_MAX = 20
_EXCERPT_CHARS = 240
_RESOURCE_KINDS = frozenset(
    {"attachment", "panel", "ocr", "measurement", "chart_figure", "chart_render"}
)


class SessionHistorySearch:
    """Search and read only source facts authorized by the calling Run."""

    __slots__ = ("_coordinator", "_execution_state")

    def __init__(
        self,
        coordinator: RunCoordinator,
        execution_state: RunExecutionStateService,
    ) -> None:
        if not isinstance(coordinator, RunCoordinator) or not isinstance(
            execution_state, RunExecutionStateService
        ):
            raise TypeError("invalid SessionHistorySearch dependencies")
        object.__setattr__(self, "_coordinator", coordinator)
        object.__setattr__(self, "_execution_state", execution_state)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SessionHistorySearch is immutable")

    def search(
        self,
        session_id: str,
        target_run_id: str,
        query: str,
        *,
        page_size: int | None = None,
        cursor: str | None = None,
        run_id: str | None = None,
        source_kind: str | None = None,
    ) -> dict[str, object]:
        if not isinstance(query, str) or not query.strip():
            raise RunError(RunErrorCode.INVALID_REQUEST)
        page_size = _page_size(page_size)
        target, prior, history, current_prefix = self._history(session_id, target_run_id)
        if run_id is not None and run_id not in {state.run.run_id for state in (*prior, target)}:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if source_kind is not None and source_kind not in {
            "message", "tool_result", "resource", *_RESOURCE_KINDS
        }:
            raise RunError(RunErrorCode.INVALID_REQUEST)

        filters = {
            "run_id": run_id,
            "source_kind": source_kind,
        }
        query_digest = hashlib.sha256(
            canonical_json_dumps({"query": query, "filters": filters}).encode("utf-8")
        ).hexdigest()
        offset = _decode_cursor(cursor, session_id, target_run_id, query_digest)

        candidates = self._candidates(
            session_id, target, prior, history, current_prefix, query,
            run_id=run_id, source_kind=source_kind,
        )
        page = candidates[offset:offset + page_size]
        next_offset = offset + len(page)
        next_cursor = (
            _encode_cursor(session_id, target_run_id, query_digest, next_offset)
            if next_offset < len(candidates)
            else None
        )
        return {
            "trust": "untrusted_history",
            "query": query,
            "matches": page,
            "next_cursor": next_cursor,
            "has_more": next_cursor is not None,
        }

    def read(
        self,
        session_id: str,
        target_run_id: str,
        reference: Mapping[str, object],
        *,
        selector: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        target, prior, _history, current_prefix = self._history(session_id, target_run_id)
        states = {state.run.run_id: state for state in prior}
        states[target.run.run_id] = current_prefix
        parsed = _parse_reference(reference)
        if isinstance(parsed, (MessageSourceRef, ToolResultSourceRef)):
            content = self._read_history_ref(parsed, states, target.run.ordinal)
        else:
            execution = self._execution_state.build(target, prior)
            content = self._read_resource(parsed, execution, session_id, states, target.run.ordinal)
        if selector is not None:
            content = _select_content(content, selector)
        return content

    def image_resource(
        self,
        session_id: str,
        target_run_id: str,
        reference: Mapping[str, object],
    ) -> tuple[RunExecutionState, ResourceRef]:
        target, prior, _history, _current_prefix = self._history(session_id, target_run_id)
        parsed = _parse_reference(reference)
        if not isinstance(parsed, (ImageResourceRef, ToolResourceRef)):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        execution = self._execution_state.build(target, prior)
        execution.get(parsed)
        return execution, parsed

    def _history(
        self, session_id: str, target_run_id: str
    ) -> tuple[RunState, tuple[RunState, ...], SessionHistory, RunState]:
        target = self._coordinator.read_run_state(session_id, target_run_id)
        prior = self._coordinator.read_prior_run_states(session_id, target_run_id)
        history = project_session_history(target.run, prior)
        current_prefix = _closed_current_prefix(target)
        return target, prior, history, current_prefix

    def _candidates(
        self,
        session_id: str,
        target: RunState,
        prior: tuple[RunState, ...],
        history: SessionHistory,
        current_prefix: RunState,
        query: str,
        *,
        run_id: str | None,
        source_kind: str | None,
    ) -> list[dict[str, object]]:
        messages = (*history.messages, *project_run_messages(current_prefix))
        states = (*prior, current_prefix)
        candidates: list[tuple[int, int, str, dict[str, object]]] = []
        order = 0
        for message in messages:
            reference = MessageSourceRef(message.run_id, message.source_record_id) if isinstance(
                message, (UserMessage, AssistantMessage)
            ) else None
            if reference is None:
                continue
            if run_id is not None and message.run_id != run_id:
                continue
            role, text, detail = _message_search_text(message)
            item = {
                "reference": reference.to_dict(),
                "run_id": message.run_id,
                "run_ordinal": message.run_ordinal,
                "source_kind": "message",
                "role": role,
                "label": role,
                "excerpt": _excerpt(text),
            }
            if _source_matches("message", source_kind) and _matches(query, text + " " + detail):
                score = _match_score(query, text + " " + detail)
                candidates.append((score, message.run_ordinal, f"{order:08d}", item))
            order += 1

        for state in states:
            for fact in state.tool_facts:
                if fact.fact_kind is not ToolFactKind.TOOL_RESULT or not isinstance(
                    fact.payload, ToolResultFact
                ):
                    continue
                result = fact.payload
                if run_id is not None and state.run.run_id != run_id:
                    continue
                source_text = tool_observation(result)
                text = f"{result.tool_name} {result.outcome.value} {source_text}"
                if not _source_matches("tool_result", source_kind) or not _matches(query, text):
                    continue
                item = {
                    "reference": ToolResultSourceRef(state.run.run_id, result.call_id).to_dict(),
                    "run_id": state.run.run_id,
                    "run_ordinal": state.run.ordinal,
                    "source_kind": "tool_result",
                    "tool_name": result.tool_name,
                    "outcome": result.outcome.value,
                    "label": result.tool_name,
                    "excerpt": _excerpt(text),
                }
                candidates.append((_match_score(query, text), state.run.ordinal, f"{order:08d}", item))
                order += 1

        for outcome in history.run_outcomes:
            if run_id is not None and outcome.run_id != run_id:
                continue
            for batch in outcome.incomplete_batches:
                for call in batch.calls:
                    text = f"{batch.assistant_text} {call.tool_name} {call.state} {call.call_id}"
                    if not _source_matches("tool_result", source_kind) or not _matches(query, text):
                        continue
                    item = {
                        "reference": ToolResultSourceRef(outcome.run_id, call.call_id).to_dict(),
                        "run_id": outcome.run_id,
                        "run_ordinal": outcome.run_ordinal,
                        "source_kind": "tool_result",
                        "tool_name": call.tool_name,
                        "outcome": call.state,
                        "label": f"{call.tool_name}（{call.state}）",
                        "excerpt": _excerpt(text),
                    }
                    candidates.append((_match_score(query, text), outcome.run_ordinal, f"{order:08d}", item))
                    order += 1

        execution = self._execution_state.build(target, prior)
        run_ordinals = {state.run.run_id: state.run.ordinal for state in (*prior, target)}
        attachment_ordinals = _attachment_ordinals((*prior, target))
        for resource in execution.resources:
            ref = resource.ref
            kind = ref.kind
            resource_run_id = (
                ref.run_id if isinstance(ref, ToolResourceRef)
                else resource.content.run_id if isinstance(resource.content, PanelContent)
                else None
            )
            ordinal = (
                run_ordinals.get(resource_run_id, target.run.ordinal)
                if resource_run_id is not None
                else attachment_ordinals.get(ref.id, target.run.ordinal)
            )
            owner_run_id = resource_run_id or _attachment_owner(ref, (*prior, target)) or target.run.run_id
            if run_id is not None and owner_run_id != run_id:
                continue
            if not _source_matches("resource", source_kind) and kind != source_kind:
                continue
            label, description = _resource_description(resource)
            if not _matches(query, label + " " + description):
                continue
            item = {
                "reference": resource_ref_to_dict(ref),
                "run_id": owner_run_id,
                "run_ordinal": ordinal,
                "source_kind": "resource",
                "resource_kind": kind,
                "label": label,
                "excerpt": _excerpt(description),
            }
            candidates.append((_match_score(query, label + " " + description), ordinal, f"{order:08d}", item))
            order += 1

        candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
        return [item[3] for item in candidates]

    def _read_history_ref(
        self,
        reference: HistorySourceRef,
        states: Mapping[str, RunState],
        target_ordinal: int,
    ) -> dict[str, object]:
        state = states.get(reference.run_id)
        if state is None or state.run.ordinal > target_ordinal:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if isinstance(reference, MessageSourceRef):
            message = next(
                (
                    item for item in project_run_messages(state)
                    if isinstance(item, (UserMessage, AssistantMessage))
                    and item.source_record_id == reference.record_id
                ),
                None,
            )
            if message is None:
                raise RunError(RunErrorCode.RUN_NOT_FOUND)
            if isinstance(message, UserMessage):
                value = {
                    "role": "user",
                    "content": message.text,
                    "attachment_ids": list(message.attachment_ids),
                }
            else:
                value = {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "call_id": call.call_id,
                            "name": call.tool_name,
                            "arguments": json.loads(call.arguments_json),
                        }
                        for call in message.tool_calls
                    ],
                }
            return {
                "trust": "untrusted_history",
                "reference": reference.to_dict(),
                "run_id": state.run.run_id,
                "run_ordinal": state.run.ordinal,
                "source_kind": "message",
                "content": value,
            }

        for fact in state.tool_facts:
            if fact.fact_kind is ToolFactKind.TOOL_RESULT and isinstance(
                fact.payload, ToolResultFact
            ) and fact.payload.call_id == reference.call_id:
                result = fact.payload
                content: dict[str, object] = {
                    "tool_name": result.tool_name,
                    "call_id": result.call_id,
                    "outcome": result.outcome.value,
                }
                if result.outcome is ToolOutcome.SUCCEEDED:
                    content["result"] = _json_value(result.result)
                elif result.error is not None:
                    content["error"] = {
                        "code": result.error.code,
                        "message": result.error.message,
                        "retryable": result.error.retryable,
                        "field_path": result.error.field_path,
                    }
                return {
                    "trust": "untrusted_history",
                    "reference": reference.to_dict(),
                    "run_id": state.run.run_id,
                    "run_ordinal": state.run.ordinal,
                    "source_kind": "tool_result",
                    "status": "committed",
                    "content": content,
                }
        if state.run.status in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
            call_state = _incomplete_call_state(state, reference.call_id)
            if call_state is not None:
                return {
                    "trust": "untrusted_history",
                    "reference": reference.to_dict(),
                    "run_id": state.run.run_id,
                    "run_ordinal": state.run.ordinal,
                    "source_kind": "tool_result",
                    "status": "unresolved",
                    "call_state": call_state,
                    "content": None,
                }
        raise RunError(RunErrorCode.RUN_NOT_FOUND)

    def _read_resource(
        self,
        reference: ResourceRef,
        execution: RunExecutionState,
        session_id: str,
        states: Mapping[str, RunState],
        target_ordinal: int,
    ) -> dict[str, object]:
        resource = execution.get(reference)
        content = resource.content
        if isinstance(content, AttachmentContent):
            run_id = _attachment_owner(reference, tuple(states.values()))
            value = {
                "filename": content.filename,
                "media_type": content.media_type,
                "byte_count": content.byte_count,
                "created_at": content.created_at,
            }
        elif isinstance(content, PanelContent):
            run_id = content.run_id
            value = {
                "name": content.name,
                "run_id": content.run_id,
                "source_attachment_id": content.source_attachment_id,
                "points": [{"x": point.x, "y": point.y} for point in content.points],
            }
        elif isinstance(content, OcrContent):
            run_id = reference.run_id
            value = _observation_value(content)
        elif isinstance(content, MeasurementContent):
            run_id = reference.run_id
            value = _observation_value(content)
        elif isinstance(content, ChartFigureContent):
            run_id = reference.run_id
            value = {
                "outcome": content.outcome.value,
                "figure": content.result.figure.to_dict() if content.result else None,
                "figure_digest": content.result.figure_digest if content.result else None,
                "error": _error_value(content.error),
            }
        elif isinstance(content, ChartRenderContent):
            run_id = reference.run_id
            value = {
                "outcome": content.outcome.value,
                "figure_ref": resource_ref_to_dict(content.figure_ref) if content.figure_ref else None,
                "result": _json_value(content.result),
                "error": _error_value(content.error),
            }
        else:
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        if run_id is not None and (
            run_id not in states or states[run_id].run.ordinal > target_ordinal
        ):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        if isinstance(content, AttachmentContent) and content.session_id != session_id:
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        return {
            "trust": "untrusted_history",
            "reference": resource_ref_to_dict(reference),
            "run_id": run_id,
            "run_ordinal": states[run_id].run.ordinal if run_id is not None else target_ordinal,
            "source_kind": "resource",
            "content": value,
        }


def _closed_current_prefix(state: RunState) -> RunState:
    """Drop the open response batch that is currently asking for retrieval."""
    response_records = [
        record for record in state.records
        if record.record_kind is RecordKind.MODEL_RESPONSE
    ]
    if not response_records:
        return state
    latest = response_records[-1]
    call_facts = [
        fact for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_CALL
        and isinstance(fact.payload, ToolCallFact)
        and fact.payload.response_record_id == latest.record_id
    ]
    if not call_facts:
        return state
    result_sequences = {
        fact.payload.tool_call_sequence for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_RESULT
    }
    if all(fact.tool_sequence in result_sequences for fact in call_facts):
        return state
    stop_at = next(index for index, item in enumerate(state.records) if item.record_id == latest.record_id)
    allowed_response_ids = {item.record_id for item in state.records[:stop_at]}
    allowed_call_sequences = {
        fact.tool_sequence for fact in state.tool_facts
        if fact.fact_kind is ToolFactKind.TOOL_CALL
        and isinstance(fact.payload, ToolCallFact)
        and fact.payload.response_record_id in allowed_response_ids
    }
    facts = tuple(
        fact for fact in state.tool_facts
        if (
            fact.fact_kind is ToolFactKind.TOOL_CALL
            and isinstance(fact.payload, ToolCallFact)
            and fact.payload.response_record_id in allowed_response_ids
        ) or (
            fact.fact_kind is not ToolFactKind.TOOL_CALL
            and getattr(fact.payload, "tool_call_sequence", None) in allowed_call_sequences
        )
    )
    return replace(state, records=state.records[:stop_at], tool_facts=facts)


def _parse_reference(value: Mapping[str, object]) -> HistorySourceRef | ResourceRef:
    if not isinstance(value, Mapping):
        raise RunError(RunErrorCode.INVALID_REQUEST)
    raw = dict(value)
    kind = raw.get("kind")
    try:
        if kind in {"message", "tool_result"}:
            return source_ref_from_dict(raw)
        if kind in {"attachment", "panel"} and set(raw) == {"kind", "id"}:
            return ImageResourceRef(kind, raw["id"])
        if kind in {"ocr", "measurement", "chart_figure", "chart_render"} and set(raw) == {
            "kind", "run_id", "call_id"
        }:
            return ToolResourceRef(kind, raw["run_id"], raw["call_id"])
    except (TypeError, ValueError):
        raise RunError(RunErrorCode.INVALID_REQUEST) from None
    raise RunError(RunErrorCode.INVALID_REQUEST)


def resource_ref_to_dict(reference: ResourceRef) -> dict[str, str]:
    if isinstance(reference, ImageResourceRef):
        return {"kind": reference.kind, "id": reference.id}
    return {"kind": reference.kind, "run_id": reference.run_id, "call_id": reference.call_id}


def _message_search_text(message: MemoryMessage) -> tuple[str, str, str]:
    if isinstance(message, UserMessage):
        detail = " ".join(message.attachment_ids)
        return "user", message.text, detail
    if isinstance(message, AssistantMessage):
        detail = " ".join(
            f"{call.tool_name} {call.call_id} {call.arguments_json}"
            for call in message.tool_calls
        )
        return "assistant", message.content, detail
    return "tool", message.content, message.tool_call_id


def _source_matches(kind: str, requested: str | None) -> bool:
    return requested is None or requested == kind or (requested == "resource" and kind == "resource")


def _matches(query: str, text: str) -> bool:
    normalized_query = query.casefold().strip()
    normalized_text = text.casefold()
    if normalized_query in normalized_text:
        return True
    terms = [term for term in re.split(r"\s+", normalized_query) if term]
    return len(terms) > 1 and all(term in normalized_text for term in terms)


def _match_score(query: str, text: str) -> int:
    normalized_query = query.casefold().strip()
    normalized_text = text.casefold()
    if normalized_query == normalized_text:
        return 3
    if normalized_query in normalized_text:
        return 2
    return 1


def _excerpt(value: str) -> str:
    flattened = " ".join(value.split())
    if len(flattened) <= _EXCERPT_CHARS:
        return flattened
    return flattened[:_EXCERPT_CHARS] + "…"


def _page_size(value: int | None) -> int:
    if value is None:
        return _PAGE_SIZE_DEFAULT
    if type(value) is not int or not 1 <= value <= _PAGE_SIZE_MAX:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    return value


def _encode_cursor(session_id: str, run_id: str, query_digest: str, offset: int) -> str:
    raw = canonical_json_dumps({
        "session_id": session_id,
        "target_run_id": run_id,
        "query_digest": query_digest,
        "offset": offset,
    }).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    value: str | None, session_id: str, run_id: str, query_digest: str
) -> int:
    if value is None:
        return 0
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        if (
            not isinstance(decoded, dict)
            or set(decoded) != {"session_id", "target_run_id", "query_digest", "offset"}
            or decoded["session_id"] != session_id
            or decoded["target_run_id"] != run_id
            or decoded["query_digest"] != query_digest
            or type(decoded["offset"]) is not int
            or decoded["offset"] < 0
        ):
            raise ValueError
        return decoded["offset"]
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError):
        raise RunError(RunErrorCode.INVALID_REQUEST) from None


def _attachment_ordinals(states: tuple[RunState, ...]) -> dict[str, int]:
    result: dict[str, int] = {}
    for state in states:
        run_input = state.records[0].payload
        for attachment_id in getattr(run_input, "attachment_ids", ()):
            result.setdefault(attachment_id, state.run.ordinal)
    return result


def _attachment_owner(reference: ResourceRef, states: tuple[RunState, ...]) -> str | None:
    if not isinstance(reference, ImageResourceRef) or reference.kind != "attachment":
        return None
    for state in states:
        run_input = state.records[0].payload
        if reference.id in getattr(run_input, "attachment_ids", ()):
            return state.run.run_id
    return None


def _resource_description(resource: object) -> tuple[str, str]:
    ref = resource.ref
    content = resource.content
    if isinstance(content, AttachmentContent):
        return content.filename, f"{content.filename} {content.media_type} {ref.id}"
    if isinstance(content, PanelContent):
        return content.name, f"{content.name} {content.source_attachment_id} {ref.id}"
    if isinstance(content, OcrContent):
        text = json.dumps(_observation_value(content), ensure_ascii=False, default=str)
        return "OCR 结果", text
    if isinstance(content, MeasurementContent):
        text = json.dumps(_observation_value(content), ensure_ascii=False, default=str)
        return content.tool_name, f"{content.tool_name} {text}"
    if isinstance(content, ChartFigureContent):
        title = content.result.figure.title if content.result else "ChartFigure"
        return title or "ChartFigure", json.dumps(_resource_content_value(content), ensure_ascii=False)
    if isinstance(content, ChartRenderContent):
        return "ChartRender", json.dumps(_resource_content_value(content), ensure_ascii=False)
    raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _resource_content_value(content: object) -> dict[str, object]:
    if isinstance(content, (OcrContent, MeasurementContent)):
        return _observation_value(content)
    if isinstance(content, ChartFigureContent):
        return {
            "outcome": content.outcome.value,
            "figure": content.result.figure.to_dict() if content.result else None,
            "figure_digest": content.result.figure_digest if content.result else None,
            "error": _error_value(content.error),
        }
    if isinstance(content, ChartRenderContent):
        return {
            "outcome": content.outcome.value,
            "figure_ref": resource_ref_to_dict(content.figure_ref) if content.figure_ref else None,
            "result": _json_value(content.result),
            "error": _error_value(content.error),
        }
    raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _observation_value(content: OcrContent | MeasurementContent) -> dict[str, object]:
    value: dict[str, object] = {
        "outcome": content.outcome.value,
        "source_ref": resource_ref_to_dict(content.source_ref) if content.source_ref else None,
        "observation_scope": _json_value(content.observation_scope),
        "result": _json_value(content.result),
        "error": _error_value(content.error),
    }
    if isinstance(content, MeasurementContent):
        value["tool_name"] = content.tool_name
    return value


def _error_value(error: object) -> dict[str, object] | None:
    if error is None:
        return None
    return {
        "code": error.code,
        "message": error.message,
        "retryable": error.retryable,
        "field_path": error.field_path,
    }


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RunError(RunErrorCode.INTEGRITY_ERROR)


def _select_content(value: dict[str, object], selector: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(selector, Mapping) or set(selector) - {"field_path", "start", "end"}:
        raise RunError(RunErrorCode.INVALID_REQUEST)
    field_path = selector.get("field_path")
    start, end = selector.get("start"), selector.get("end")
    if field_path is not None:
        if not isinstance(field_path, str) or (field_path and not field_path.startswith("/")):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        node: object = value.get("content")
        for segment in field_path.lstrip("/").split("/") if field_path else ():
            segment = segment.replace("~1", "/").replace("~0", "~")
            if isinstance(node, Mapping) and segment in node:
                node = node[segment]
            elif isinstance(node, (tuple, list)) and segment.isdigit() and int(segment) < len(node):
                node = node[int(segment)]
            else:
                raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        selected = node
    else:
        selected = value.get("content")
    if start is not None or end is not None:
        if (
            type(start) not in (int, type(None))
            or type(end) not in (int, type(None))
            or (start is not None and start < 0)
            or (end is not None and end < 0)
        ):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        if not isinstance(selected, (str, tuple, list)):
            raise RunError(RunErrorCode.UNSUPPORTED_PAYLOAD)
        selected = selected[start:end]
    result = dict(value)
    result["content"] = _json_value(selected)
    if field_path is not None:
        result["selected_field"] = field_path
    return result


def _incomplete_call_state(state: RunState, call_id: str) -> str | None:
    messages = project_run_messages_for_abnormal(state)
    for batch in messages:
        for call in batch:
            if call[0] == call_id:
                return call[1]
    return None


def project_run_messages_for_abnormal(state: RunState) -> tuple[tuple[tuple[str, str], ...], ...]:
    from .projector import IncompleteBatchContext

    batches: list[IncompleteBatchContext] = []
    # The terminal source Run is validated by the caller's state read. Re-project
    # it with abnormal-tail collection so unresolved calls stay source-addressable.
    from .projector import _project_run_messages

    _project_run_messages(state, batches)
    return tuple(
        tuple((call.call_id, call.state) for call in batch.calls)
        for batch in batches
    )
