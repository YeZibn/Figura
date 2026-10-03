import pytest

from figura.shared.payloads import (
    ExecutionPayloadLimits, PayloadError, decode_json, encode_json,
    opaque_call_id, use_payload_limits,
)
from figura.shared.json_schema import validate_instance, validate_schema_definition


def test_utf8_complete_payload_guard_and_context_isolation():
    with use_payload_limits(ExecutionPayloadLimits(11)):
        assert encode_json({"x": "中"}) == '{"x":"中"}'
        with pytest.raises(PayloadError):
            encode_json({"x": "中文"})
    assert encode_json({"x": "中文"}) == '{"x":"中文"}'


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}', '"\\ud800"'])
def test_strict_json_rejects_unsafe_values(raw):
    with pytest.raises(PayloadError):
        decode_json(raw)


def test_actual_container_depth_is_bounded_before_parsing():
    raw = '[' * 65 + '0' + ']' * 65
    assert encode_json(decode_json(raw)) == raw
    with pytest.raises(PayloadError):
        decode_json('[' + raw + ']')
    assert decode_json('"[{}]"') == '[{}]'


def test_large_schema_properties_enum_and_domain_constraints():
    properties = {f"p{i}": {"type": "integer"} for i in range(300)}
    schema = validate_schema_definition({"type": "object", "properties": properties})
    assert validate_instance({f"p{i}": i for i in range(300)}, schema) is None
    enum = validate_schema_definition({"type": "integer", "enum": list(range(300))})
    assert validate_instance(299, enum) is None
    assert validate_instance([1, 2], {"type": "array", "maxItems": 1}).code == "max_items"


def test_long_opaque_call_id_and_invalid_configuration():
    assert opaque_call_id('调用-' * 100) == '调用-' * 100
    for value in ('0', '-1', 'NaN', '1.5'):
        with pytest.raises(PayloadError):
            ExecutionPayloadLimits.from_env({'FIGURA_EXECUTION_PAYLOAD_MAX_BYTES': value})
