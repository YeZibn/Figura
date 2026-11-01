"""Single text projection of a canonical tool observation."""
from figura.shared.json_schema import canonical_json_dumps
from figura.shared.media import attachment_to_dict
from .contracts import ToolOutcome


def observation_data(result) -> dict[str, object]:
    payload = {'outcome': result.outcome.value,
               'attachments': [attachment_to_dict(item) for item in result.attachments]}
    if result.outcome is ToolOutcome.SUCCEEDED:
        if result.result is None or result.error is not None:
            raise ValueError('invalid successful observation')
        payload['result'] = result.result
    else:
        if result.error is None or result.result is not None or result.attachments:
            raise ValueError('invalid failed observation')
        error = {'code': result.error.code, 'message': result.error.message,
                 'retryable': result.error.retryable}
        if result.error.field_path is not None:
            error['field_path'] = result.error.field_path
        payload['error'] = error
    return payload


def observation_json(result) -> str:
    return canonical_json_dumps(observation_data(result))
