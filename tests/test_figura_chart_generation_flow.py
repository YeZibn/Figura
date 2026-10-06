"""Offline regression of two Runs through real tools and Provider payloads."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from tests.figura_sources_support import make_attachment_service, make_panel_service, make_execution_image_reader
from tests.test_figura_agent_executor import _multi_provider_runtime, _agent
from tests.test_figura_bar_measurement_tool import _chart_bytes
from tests.test_figura_chart_rendering import _chart_spec
from figura.agent.execution_state import RunExecutionStateService
from figura.agent.request import AgentRequestBuilder
from figura.providers import ProviderId, MODEL_IDS
from figura.runtime.models import RunCreateRequest, RunStatus
from figura.sources.chart_renders import FiguraChartRenderService
from figura.tools import ToolRegistry
from figura.tools.implementations.measure_chart import measure_chart_definition
from figura.tools.implementations.assemble_chart_figure import assemble_chart_figure_definition
from figura.tools.implementations.render_chart_figure import render_chart_figure_definition
from figura.tools.measurements.family_adapters import current_chart_family_adapters
from figura.gateway.web_projection import run_summary


class ScriptTransport:
    def __init__(self):
        self.responses = []
        self.calls = []

    def create(self, **payload):
        self.calls.append(payload)
        return self.responses.pop(0)


def response(name=None, arguments=None, *, call_id='call', reasoning='private', present=True):
    message = {'content': '完成' if name is None else ''}
    if present:
        message['reasoning_content'] = reasoning
    if name:
        message['tool_calls'] = [{'id': call_id, 'function': {'name': name, 'arguments': json.dumps(arguments)}}]
    return {'choices': [{'message': message, 'finish_reason': 'tool_calls' if name else 'stop'}]}


@pytest.mark.parametrize('reasoning,present', [(None,True), ('',True), ('private',True), (None,False)])
def test_two_run_measure_assemble_render_observe_flow(tmp_path, reasoning, present):
    transport = ScriptTransport()
    store, coordinator, session, factory = _multi_provider_runtime(tmp_path, transport)
    attachments = make_attachment_service(store)
    panels = make_panel_service(store, attachments)
    renders = FiguraChartRenderService(tmp_path)
    state_service = RunExecutionStateService(coordinator, panels)
    reader = make_execution_image_reader(attachments, panels, renders)
    registry = ToolRegistry('figura-web-v9', (
        measure_chart_definition(state_service.for_run, reader, current_chart_family_adapters()),
        assemble_chart_figure_definition(state_service.for_run),
        render_chart_figure_definition(state_service.for_run, renders),
    ))
    attachment = attachments.upload(session.session_id, 'bars.png', _chart_bytes())
    def new_run(key, ids=()):
        return coordinator.create_run(RunCreateRequest(session_id=session.session_id, text=key,
            provider_id='deepseek', model_id=MODEL_IDS[ProviderId.DEEPSEEK], idempotency_key=key, attachment_ids=ids))
    first = new_run('measure', (attachment.attachment_id,))
    transport.responses = [response('measure_chart', {'source_kind': 'attachment', 'source_id': attachment.attachment_id, 'chart_type': 'bar'}, call_id='measurement'), response()]
    agent = _agent(store, coordinator, registry, factory, AgentRequestBuilder(state_service, reader))
    assert agent.execute(session.session_id, first.run_id).run.status is RunStatus.COMPLETED
    assert len(state_service.for_run(session.session_id, first.run_id).list('measurement')) == 1
    second = new_run('generate')
    figure = {'schema_version':2, 'title':'季度销售占比', 'layout':{'columns':2}, 'charts':[
        {'chart_id':str(i), 'chart_spec':_chart_spec('pie'), 'measurement_refs':[{'run_id':first.run_id, 'call_id':'measurement'}]} for i in range(2)]}
    invalid = deepcopy(figure)
    invalid['charts'][0]['chart_spec']['dataset']['unexpected'] = 'Target'
    transport.responses = [response('assemble_chart_figure', invalid, call_id='invalid'),
        response('assemble_chart_figure', figure, call_id='accepted'),
        response('render_chart_figure', {'figure_ref':{'run_id':second.run_id, 'call_id':'accepted'}},
            call_id='render', reasoning=reasoning, present=present), response()]
    state = agent.execute(session.session_id, second.run_id)
    resource = state_service.for_run(session.session_id, second.run_id).list('chart_render')[0]
    assert resource.content.result is not None
    assert renders.resolve(second.run_id, 'render')[0].startswith(b'\x89PNG')
    results = [fact.payload for fact in state.tool_facts if fact.fact_kind.value == 'tool_result']
    assert results[0].error.code == 'invalid_arguments'
    if present:
        assert state.run.status is RunStatus.COMPLETED
        wire = transport.calls[-1]['messages']
        render_assistant = next(m for m in wire if m.get('tool_calls', [{}])[0].get('id') == 'render')
        assert render_assistant['reasoning_content'] == reasoning
        assert any(isinstance(m['content'], list) and any(b.get('type')=='image_url' for b in m['content']) for m in wire)
        assert state.run.final_record_id is not None
    else:
        assert state.run.status is RunStatus.FAILED
        assert len(state.provider_attempts) == 3
        assert state.run.final_record_id is None
        assert '缺少必要' in state.run.terminal_message
        assert run_summary(state)['terminalMessage'] == state.run.terminal_message
    assert len(transport.calls) == (6 if present else 5)
