"""Native TOOL image payload, capability rejection and token occurrence tests."""
from dataclasses import replace
from types import MappingProxyType

import pytest

from figura.providers import ImageBlock, MessageRole, ProviderMessage, ProviderToolCall, ProviderId, TextBlock
from figura.providers.errors import ProviderInputError, ProviderFailureCode
from figura.providers.token_estimation import input_projection, estimate_input
from tests.test_figura_provider import _factory, FakeTransport, _response, _request
from tests.test_figura_tool_media import _image


def _native_request(provider=ProviderId.DEEPSEEK):
    image = _image()
    ref = MappingProxyType({'kind': 'attachment', 'id': 'original-source'})
    block = ImageBlock(image.media_type, image.image_bytes, ref)
    return _request(provider, thinking_mode=False, messages=(
        ProviderMessage(MessageRole.USER, 'Inspect both returned images.'),
        ProviderMessage(MessageRole.ASSISTANT, '', tool_calls=(
            ProviderToolCall('a', 'read', '{}'), ProviderToolCall('b', 'read', '{}'), ProviderToolCall('c', 'read', '{}'))),
        ProviderMessage(MessageRole.TOOL, (TextBlock('{"outcome":"succeeded"}'), TextBlock('hint A'), block), tool_call_id='a'),
        ProviderMessage(MessageRole.TOOL, (TextBlock('{"outcome":"succeeded"}'), TextBlock('hint B'), block), tool_call_id='b'),
        ProviderMessage(MessageRole.TOOL, '{"outcome":"failed","attachments":[]}', tool_call_id='c'),
    ))


def test_deepseek_keeps_native_tool_identity_order_and_repeated_image_occurrences():
    transport = FakeTransport(_response()); request = _native_request()
    client = _factory(transport).create(request.provider_id, request.model_id)
    prepared = client.prepare(request)
    messages = prepared.payload['messages']
    assert [m['role'] for m in messages] == ['user', 'assistant', 'tool', 'tool', 'tool']
    assert [m['tool_call_id'] for m in messages[2:]] == ['a', 'b', 'c']
    for message, hint in zip(messages[2:4], ['hint A', 'hint B'], strict=True):
        assert [part['type'] for part in message['content']] == ['text', 'text', 'image_url']
        assert message['content'][1]['text'] == hint
        assert message['content'][2]['image_url']['url'].startswith('data:image/png;base64,')
    manifest = prepared.descriptor['asset_manifest']
    assert len(manifest['images']) == 2
    assert manifest['images'][0] == manifest['images'][1]
    assert set(manifest) == {'prompt_digest', 'registry_version', 'registry_digest', 'adapter_contract_version', 'images'}
    again = client.prepare(request)
    assert prepared.descriptor == again.descriptor and prepared.payload == again.payload
    client.dispatch(prepared); client.dispatch(again)
    assert transport.calls[0] == transport.calls[1]


@pytest.mark.parametrize('provider', [ProviderId.QWEN, ProviderId.MIMO])
def test_unverified_providers_refuse_images_and_visual_tools_before_dispatch(provider):
    transport = FakeTransport(_response()); request = _native_request(provider)
    client = _factory(transport).create(provider, request.model_id)
    with pytest.raises(ProviderInputError) as error: client.prepare(request)
    assert error.value.failure.failure_code is ProviderFailureCode.UNSUPPORTED_CAPABILITY
    assert transport.calls == []
    first = replace(_request(provider, thinking_mode=False), asset_contract={'requires_tool_result_images': True})
    with pytest.raises(ProviderInputError): client.prepare(first)
    assert transport.calls == []


def test_pixels_hint_role_and_call_identity_all_change_request_binding():
    request = _native_request(); client = _factory(FakeTransport()).create(request.provider_id, request.model_id)
    before = client.prepare(request).descriptor['request_fingerprint']
    original = request.messages[2]
    for blocks in [
        (original.content[0], TextBlock('changed hint'), original.content[2]),
        (original.content[0], original.content[1], replace(original.content[2], image_bytes=_image('green').image_bytes)),
        tuple(reversed(original.content)),
    ]:
        modified = replace(request, messages=(*request.messages[:2], replace(original, content=blocks), *request.messages[3:]))
        assert client.prepare(modified).descriptor['request_fingerprint'] != before


def test_token_estimator_excludes_base64_and_counts_tool_images_and_hints():
    request = _native_request(); client = _factory(FakeTransport()).create(request.provider_id, request.model_id)
    payload = client.prepare(request).payload
    projection, count = input_projection(payload)
    assert count == 2
    assert 'base64,' not in str(projection)
    assert 'hint A' in str(projection) and 'hint B' in str(projection)
    class Encoding:
        def encode_ordinary(self, text): return [0] * len(text)
    estimate = estimate_input(payload, None, Encoding())
    import json
    text = json.dumps(projection, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':'))
    assert estimate.input_tokens == len(text) + 2048
    # Metadata-only earlier observations have no visual charge.
    _, unloaded = input_projection({'messages': [{'role': 'tool', 'content': '{"attachments":[{"sha256":"abc"}],"images_loaded":false}'}]})
    assert unloaded == 0


def test_closed_batches_can_reuse_an_opaque_call_id_without_changing_source_identity():
    request = _native_request()
    repeated = replace(request, messages=(
        ProviderMessage(MessageRole.USER, 'earlier Run'),
        ProviderMessage(MessageRole.ASSISTANT, '', tool_calls=(ProviderToolCall('a', 'read', '{}'),)),
        ProviderMessage(MessageRole.TOOL, 'earlier result', tool_call_id='a'),
        *request.messages,
    ))
    client = _factory(FakeTransport()).create(repeated.provider_id, repeated.model_id)
    prepared = client.prepare(repeated)
    assert [m['tool_call_id'] for m in prepared.payload['messages'] if m['role']=='tool'] == ['a','a','b','c']
