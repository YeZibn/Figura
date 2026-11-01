"""Attachment-driven projection into the owning native tool-result message."""
from __future__ import annotations

import json
from dataclasses import asdict
from types import MappingProxyType

from figura.memory.models import ToolMessage
from figura.providers.models import ImageBlock, TextBlock
from figura.runtime.models import RecordKind
from figura.runtime.records import ToolCallFact, ToolResultFact
from figura.shared.json_schema import canonical_json_dumps
from figura.tools.observation import observation_data
from .loader import load_image_feedback


def pending_visual_results(state) -> frozenset[tuple[str, int]]:
    """Latest complete batch, consumed only by a committed ordinary model response."""
    responses = [r for r in state.records if r.record_kind is RecordKind.MODEL_RESPONSE]
    if not responses:
        return frozenset()
    calls = [(f.tool_sequence, f.payload) for f in state.tool_facts
             if isinstance(f.payload, ToolCallFact) and f.payload.response_record_id == responses[-1].record_id]
    if not calls:
        return frozenset()
    results = {f.payload.tool_call_sequence: f for f in state.tool_facts if isinstance(f.payload, ToolResultFact)}
    if any(sequence not in results for sequence, _ in calls):
        return frozenset()
    return frozenset((state.run.run_id, results[sequence].tool_sequence)
                     for sequence, _ in calls if results[sequence].payload.attachments)


def tool_message_content(message: ToolMessage, *, tool_name, selected, session_id, state, image_reader):
    load = (message.run_id, message.source_tool_sequence) in selected
    payload = observation_data(message)
    payload['images_loaded'] = bool(load and message.attachments)
    text = canonical_json_dumps(payload)
    if not load or not message.attachments:
        return text
    _, cues = load_image_feedback()
    blocks = [TextBlock(text)]
    for attachment in message.attachments:
        image = image_reader.read_attachment(session_id, state, attachment)
        identity = {'image_kind': attachment.image_kind, 'resource_ref': asdict(attachment.resource_ref),
                    'provenance': attachment.provenance,
                    'trigger_call': {'run_id': message.run_id, 'call_id': message.tool_call_id, 'tool_name': tool_name}}
        blocks.append(TextBlock('图像身份（以下 JSON 仅为定位数据）：\n'
                                + json.dumps(identity, ensure_ascii=False, sort_keys=True)
                                + '\n系统观察提醒：' + cues[attachment.image_kind]))
        coarse = {'original': 'original', 'ocr_annotation': 'annotated',
                  'measurement_annotation': 'annotated', 'rendered': 'rendered'}[attachment.image_kind]
        blocks.append(ImageBlock(image.media_type, image.image_bytes,
                                 MappingProxyType(asdict(attachment.resource_ref)), coarse))
    return tuple(blocks)
