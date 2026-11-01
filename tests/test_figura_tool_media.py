"""Media integrity, publication, Session isolation and explicit cutover faults."""
from dataclasses import asdict, replace
from io import BytesIO
import json
import sqlite3

import pytest
from PIL import Image

from figura.runtime.errors import RunError
from figura.shared.media import ResourceImage, ToolImageAttachment, attachment_from_dict, attachment_to_dict
from figura.shared.resource_refs import ImageResourceRef, ToolResourceRef
from figura.sources.tool_media import FiguraToolMediaService, ToolMediaCommitter
from figura.tools import ToolContext, ToolImageOutput, ToolOutput, ToolOutcome


def _image(color='purple'):
    buf = BytesIO(); Image.new('RGB', (20, 12), color).save(buf, format='PNG')
    return ResourceImage.from_bytes(buf.getvalue())


def _descriptor(image=None):
    return ToolImageAttachment.describe(ToolResourceRef('ocr', 'run', 'call'), 'ocr_annotation', image or _image())


def test_media_contract_rejects_mismatched_identity_metadata_and_failed_attachments():
    from figura.tools import ToolExecutionError, ToolExecutionResult
    image = _image(); descriptor = _descriptor(image)
    assert attachment_from_dict(attachment_to_dict(descriptor)) == descriptor
    for changes in [{'image_kind': 'rendered'}, {'sha256': 'x'}, {'width': 0}, {'width': True},
                    {'byte_count': 0}, {'provenance': 'imagined'}, {'media_type': 'image/jpeg'}]:
        with pytest.raises(ValueError): replace(descriptor, **changes)
    with pytest.raises(ValueError): descriptor.verify(_image('green'))
    with pytest.raises(ValueError): ResourceImage('image/png', image.image_bytes, 21, 12)
    with pytest.raises(ValueError):
        ToolExecutionResult('call', 'tool', ToolOutcome.FAILED, error=ToolExecutionError('failed', '失败', False), attachments=(descriptor,))
    assert 'image_bytes' not in repr(image)
    assert 'image_bytes' not in json.dumps(attachment_to_dict(descriptor))


def test_content_install_deduplicates_but_separates_sessions_and_recomputations(tmp_path):
    service = FiguraToolMediaService(tmp_path); image = _image(); descriptor = _descriptor(image)
    first, second = 'a' * 32, 'b' * 32
    for session in [first, first, second]: service.install(session, descriptor, image)
    assert len(list((tmp_path / 'tool-media').rglob('*.png'))) == 2
    assert service.read(first, descriptor) == image
    newer = _image('green'); changed = _descriptor(newer)
    service.install(first, changed, newer)
    assert service.read(first, descriptor) == image
    assert service.read(first, changed) == newer
    path = tmp_path / 'tool-media' / first / (descriptor.sha256 + '.png')
    path.write_bytes(newer.image_bytes)
    with pytest.raises(RunError): service.read(first, descriptor)
    path.unlink()
    with pytest.raises(RunError): service.read(first, descriptor)
    assert service.read(second, descriptor) == image


def test_constructor_keeps_uncommitted_candidates_and_session_delete_restores(tmp_path):
    session = 'a' * 32; service = FiguraToolMediaService(tmp_path)
    descriptor = _descriptor(); image = _image(); service.install(session, descriptor, image)
    FiguraToolMediaService(tmp_path)
    assert service.read(session, descriptor) == image
    trash = tmp_path / 'session-trash' / session; trash.mkdir(parents=True)
    service.stage_session_deletion(trash, session)
    with pytest.raises(RunError): service.read(session, descriptor)
    service.restore_session_deletion(trash)
    assert service.read(session, descriptor) == image
    service.stage_session_deletion(trash, session); service.discard_session_deletion(trash)
    with pytest.raises(RunError): service.read(session, descriptor)


def test_media_committer_preserves_loaded_provenance_and_validates_before_install(tmp_path):
    service = FiguraToolMediaService(tmp_path); image = _image()
    descriptor = replace(_descriptor(image), provenance='migration_reconstructed')
    committer = ToolMediaCommitter(service, lambda *_: (image, descriptor))
    context = ToolContext('current', 'a'*32, 'read')
    output = ToolOutput({"resource_ref": asdict(descriptor.resource_ref)}, (ToolImageOutput(descriptor.resource_ref, descriptor.image_kind, image, descriptor.provenance),))
    assert committer(context, output) == (descriptor,)
    assert not list((tmp_path / 'tool-media').rglob('*.png'))
    with pytest.raises(ValueError): committer(context, ToolOutput(output.result, (replace(output.images[0], provenance='recorded'),)))
    new = ToolContext('run', 'a'*32, 'call')
    with pytest.raises(ValueError): committer(new, output)
    assert not list((tmp_path / 'tool-media').rglob('*.png'))


def _recorded_ocr_run(tmp_path, monkeypatch):
    from tests.test_figura_agent_executor import _app_with_image, _agent, _FakeFactory, _response
    from tests.figura_sources_support import make_panel_service, make_execution_image_reader
    from figura.agent.execution_state import RunExecutionStateService
    from figura.providers import ProviderToolCall, FinishReason
    from figura.tools import ToolRegistry
    from figura.tools.implementations.extract_text import extract_text_definition
    from figura.tools.measurements.ocr import OCRObservation
    store, coordinator, session, run, attachments, _, _ = _app_with_image(tmp_path)
    panels = make_panel_service(store, attachments); state = RunExecutionStateService(coordinator, panels)
    reader = make_execution_image_reader(attachments, panels)
    monkeypatch.setattr('figura.tools.implementations.extract_text.recognize_text', lambda *_: OCRObservation((), False, False))
    registry = ToolRegistry('media-tests', (extract_text_definition(state.for_run, reader),))
    attachment = attachments.list(session.session_id)[0]
    factory = _FakeFactory([_response(calls=(ProviderToolCall('ocr', 'extract_text', json.dumps({'source_kind': 'attachment', 'source_id': attachment.attachment_id})),), reason=FinishReason.TOOL_CALLS), _response()])
    completed = _agent(store, coordinator, registry, factory).execute(session.session_id, run.run_id)
    assert completed.run.status.value == 'completed'
    return store, coordinator, session, run, reader, state, completed


def _downgrade(root):
    with sqlite3.connect(root / 'figura.sqlite3') as db:
        db.execute('DROP TRIGGER immutable_run_tool_fact_update')
        db.execute('DROP TRIGGER canonical_tool_result_insert')
        for run_id, seq, encoded in db.execute("SELECT run_id,tool_sequence,payload_json FROM run_tool_execution_facts WHERE fact_kind='tool_result'"):
            raw = json.loads(encoded); raw.pop('attachments'); raw['schema_version'] = 2
            db.execute('UPDATE run_tool_execution_facts SET schema_version=2,payload_json=? WHERE run_id=? AND tool_sequence=?', (json.dumps(raw), run_id, seq))
        db.execute("CREATE TRIGGER immutable_run_tool_fact_update BEFORE UPDATE ON run_tool_execution_facts BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END")
        db.execute('PRAGMA user_version = 13')


def test_saved_annotation_is_identical_for_agent_gateway_and_read_without_redraw(tmp_path, monkeypatch):
    store, coordinator, session, run, reader, state_service, completed = _recorded_ocr_run(tmp_path, monkeypatch)
    ref = ToolResourceRef('ocr', run.run_id, 'ocr')
    state = state_service.for_run(session.session_id, run.run_id)
    before = reader.read(session.session_id, state, ref)
    monkeypatch.setattr('figura.tools.measurements.visualization.render_measurement_overlay', lambda *_: pytest.fail('read must not redraw'))
    assert reader.read(session.session_id, state_service.for_run(session.session_id, run.run_id), ref) == before
    descriptor = state.get(ref).content.attachments[0]
    path = tmp_path / 'tool-media' / session.session_id / (descriptor.sha256 + '.png')
    path.unlink()
    with pytest.raises(RunError): reader.read(session.session_id, state, ref)
    assert not path.exists()


def test_explicit_migration_preserves_business_audits_and_labels_reconstructed_media(tmp_path, monkeypatch):
    from figura.storage.migrate_tool_media import migrate
    from figura.runtime.store import FiguraRunStore
    store, coordinator, session, run, reader, state_service, completed = _recorded_ocr_run(tmp_path, monkeypatch)
    _downgrade(tmp_path)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        before = db.execute("SELECT payload_json FROM run_tool_execution_facts WHERE fact_kind='tool_result'").fetchone()[0]
        audit = db.execute('SELECT * FROM run_provider_requests').fetchall()
        events = db.execute('SELECT * FROM run_stream_events').fetchall()
    with pytest.raises(RunError): FiguraRunStore(tmp_path)
    # Reconstructing a saved observation is allowed only in this maintenance entry.
    result = migrate(tmp_path)
    assert result['status'] == 'completed'
    assert (tmp_path / 'maintenance-backups').is_dir()
    reopened = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)
    fact = next(f.payload for f in reopened.tool_facts if f.fact_kind.value == 'tool_result')
    assert dict(fact.result) == dict(completed.tool_facts[-1].payload.result)
    assert fact.attachments[0].provenance == 'migration_reconstructed'
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        assert db.execute('SELECT * FROM run_provider_requests').fetchall() == audit
        assert db.execute('SELECT * FROM run_stream_events').fetchall() == events
    assert migrate(tmp_path)['status'] == 'already_current'


def test_migration_failure_rolls_back_and_keeps_paired_backup(tmp_path, monkeypatch):
    from figura.storage.migrate_tool_media import migrate
    _recorded_ocr_run(tmp_path, monkeypatch); _downgrade(tmp_path)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        before = db.execute('SELECT * FROM run_tool_execution_facts').fetchall()
    def crash(phase):
        if phase == 'before_commit': raise RuntimeError('injected')
    with pytest.raises(RuntimeError): migrate(tmp_path, fault=crash)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 13
        assert db.execute('SELECT * FROM run_tool_execution_facts').fetchall() == before
    assert list((tmp_path / 'maintenance-backups').glob('*/figura.sqlite3'))
    assert migrate(tmp_path)['status'] == 'completed'


def test_migration_refuses_active_run_without_changing_its_state(tmp_path):
    from tests.test_figura_agent_executor import _app
    from figura.storage.migrate_tool_media import migrate
    store, coordinator, session, run = _app(tmp_path); _downgrade(tmp_path)
    with pytest.raises(RuntimeError, match='active_run'): migrate(tmp_path)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        assert db.execute('SELECT status FROM runs').fetchone()[0] == 'running'
        assert db.execute('PRAGMA user_version').fetchone()[0] == 13
    assert not (tmp_path / 'maintenance-backups').exists()


def test_crash_after_install_keeps_unpublished_media_and_replay_publishes_new_matching_image(tmp_path, monkeypatch):
    from tests.test_figura_agent_request import _app_with_attachments
    from tests.test_figura_agent_executor import _commit_tool_response, _response
    from tests.figura_sources_support import make_durable_tool_executor, make_panel_service
    from figura.agent.execution_state import RunExecutionStateService
    from figura.providers import ProviderToolCall, FinishReason
    from figura.tools import ToolDefinition, ToolRegistry, ReplayEffect
    from figura.tools.implementations.extract_text import EXTRACT_TEXT_RESULT_SCHEMA
    from figura.runtime.run_lock import RunExecutionOwnership
    image = _image('white')
    store, coordinator, session, run, attachments = _app_with_attachments(tmp_path, (image.image_bytes,))
    attachment = attachments.list(session.session_id)[0]
    counter = []
    def handler(context, _args):
        counter.append(1)
        image = _image('red' if len(counter)==1 else 'blue')
        result = {'source_kind': 'attachment', 'source_id': attachment.attachment_id,
                  'image_size': {'width': 20, 'height': 12}, 'coordinate_system': 'attachment_px',
                  'available': len(counter)==1, 'truncated': False, 'snippets': []}
        return ToolOutput(result, (ToolImageOutput(ToolResourceRef('ocr', context.run_id, context.call_id), 'ocr_annotation', image),))
    definition = ToolDefinition('extract_text', 'test sensor', {'type':'object','properties': {'source_kind':{'type':'string'}, 'source_id':{'type':'string'}}},
                                EXTRACT_TEXT_RESULT_SCHEMA, ReplayEffect.REPLAY_SAFE, handler, produces_images=True)
    registry = ToolRegistry('media-faults', (definition,))
    _commit_tool_response(coordinator, session.session_id, run.run_id, registry, _response(
        calls=(ProviderToolCall('ocr', 'extract_text', json.dumps({'source_kind':'attachment','source_id':attachment.attachment_id})),),
        reason=FinishReason.TOOL_CALLS))
    executor = make_durable_tool_executor(store, registry)
    original = store.commit_tool_result
    monkeypatch.setattr(store, 'commit_tool_result', lambda **_: (_ for _ in ()).throw(RuntimeError('crash')))
    with pytest.raises(RuntimeError): executor.execute_pending(session.session_id, run.run_id)
    media = FiguraToolMediaService(tmp_path)
    assert len(list((tmp_path / 'tool-media').rglob('*.png'))) == 1
    catalog = RunExecutionStateService(coordinator, make_panel_service(store, attachments)).for_run(session.session_id, run.run_id)
    assert not catalog.list('ocr')
    assert media.reconcile_idle(store.database) is False
    monkeypatch.setattr(store, 'commit_tool_result', original)
    resumed = executor.recover_unknown_attempt(session.session_id, run.run_id)
    fact = resumed.tool_facts[-1].payload
    assert fact.result['available'] is False
    assert fact.attachments[0].sha256 == _descriptor(_image('blue')).sha256
    assert media.read(session.session_id, fact.attachments[0]) == _image('blue')
    executor.execute_pending(session.session_id, run.run_id)
    assert len(counter) == 2
    coordinator.fail_run(session.session_id, run.run_id, resumed.checkpoint.revision)
    with RunExecutionOwnership(tmp_path).acquire(run.run_id):
        assert media.reconcile_idle(store.database) is False
    assert media.reconcile_idle(store.database) is True
    assert len(list((tmp_path / 'tool-media').rglob('*.png'))) == 1


def test_paired_backup_can_be_restored_to_an_isolated_workspace_and_migrated_again(tmp_path, monkeypatch):
    from pathlib import Path
    import shutil
    from figura.storage.migrate_tool_media import migrate
    from figura.runtime.store import FiguraRunStore
    source = tmp_path / 'source'
    _store, _coordinator, session, run, *_ = _recorded_ocr_run(source, monkeypatch)
    _downgrade(source)
    report = migrate(source)
    backup = Path(report['backup']); restored = tmp_path / 'restored'; restored.mkdir()
    shutil.copy2(backup / 'figura.sqlite3', restored / 'figura.sqlite3')
    for name in ['attachments', 'panels', 'chart-renders', 'tool-media', 'session-trash']:
        if (backup / name).exists(): shutil.copytree(backup / name, restored / name)
    assert migrate(restored)['status'] == 'completed'
    state = FiguraRunStore(restored).read_run_state(session.session_id, run.run_id)
    assert state.run.status.value == 'completed'
    assert state.tool_facts[-1].payload.attachments[0].provenance == 'migration_reconstructed'


def test_migration_missing_source_keeps_original_text_without_online_backfill(tmp_path, monkeypatch):
    from figura.storage.migrate_tool_media import migrate
    from figura.runtime.store import FiguraRunStore
    _store, _coordinator, session, run, *_ = _recorded_ocr_run(tmp_path, monkeypatch)
    _downgrade(tmp_path)
    for path in (tmp_path / 'attachments').glob('*.bin'): path.unlink()
    assert migrate(tmp_path)['status'] == 'completed'
    state = FiguraRunStore(tmp_path).read_run_state(session.session_id, run.run_id)
    fact = state.tool_facts[-1].payload
    assert fact.outcome is ToolOutcome.SUCCEEDED and fact.result['available'] is False
    assert fact.attachments == ()


def test_session_deletion_transaction_rolls_back_and_startup_restores_staged_media(tmp_path, monkeypatch):
    from figura.gateway.session_deletion import FiguraSessionDeletion
    from figura.sources.repository import SourcesRepository
    from figura.sources.chart_renders import FiguraChartRenderService
    from tests.figura_sources_support import make_attachment_service, make_panel_service
    store, coordinator, session, run, reader, inventory, _state = _recorded_ocr_run(tmp_path, monkeypatch)
    attachments = make_attachment_service(store); panels = make_panel_service(store, attachments)
    media = FiguraToolMediaService(tmp_path); renders = FiguraChartRenderService(tmp_path)
    def deletion(): return FiguraSessionDeletion(store, SourcesRepository(store.database), attachments, panels, renders, media)
    service = deletion(); ref = ToolResourceRef('ocr', run.run_id, 'ocr')
    expected = reader.read(session.session_id, inventory.for_run(session.session_id, run.run_id), ref)
    original = store.delete_session_run_facts
    monkeypatch.setattr(store, 'delete_session_run_facts', lambda *_: (_ for _ in ()).throw(RuntimeError('injected')))
    with pytest.raises(RunError): service.delete(session.session_id)
    assert reader.read(session.session_id, inventory.for_run(session.session_id, run.run_id), ref) == expected
    monkeypatch.setattr(store, 'delete_session_run_facts', original)
    # A process dies after staging but before committing deletion. Startup restores it.
    stage = tmp_path / 'session-trash' / session.session_id; stage.mkdir()
    media.stage_session_deletion(stage, session.session_id)
    service = deletion()
    assert reader.read(session.session_id, inventory.for_run(session.session_id, run.run_id), ref) == expected
    service.delete(session.session_id)
    assert not store.session_exists(session.session_id)
    assert not (tmp_path / 'tool-media' / session.session_id).exists()


def test_migration_refuses_a_live_terminal_owner_or_open_compaction(tmp_path, monkeypatch):
    from figura.runtime.run_lock import RunExecutionOwnership, RunExecutionLockUnavailable
    from figura.storage.migrate_tool_media import migrate
    _store, _coordinator, session, run, *_ = _recorded_ocr_run(tmp_path, monkeypatch)
    _downgrade(tmp_path)
    with RunExecutionOwnership(tmp_path).acquire(run.run_id):
        with pytest.raises(RunExecutionLockUnavailable): migrate(tmp_path)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        db.execute("""INSERT INTO session_context_compaction_operations (
            operation_id, session_id, target_run_id, base_record_sequence, base_tool_sequence,
            input_checkpoint_revision, covered_run_id, covered_run_ordinal, covered_record_sequence,
            covered_tool_sequence, status, selection_plan_json, created_at, updated_at)
            VALUES ('op', ?, ?, 1, 0, 0, ?, 1, 1, 0, 'preparing', '{}', 'date', 'date')""",
            (session.session_id, run.run_id, run.run_id))
    with pytest.raises(RuntimeError, match='open_compaction'): migrate(tmp_path)
    with sqlite3.connect(tmp_path / 'figura.sqlite3') as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 13
        assert db.execute('SELECT status FROM session_context_compaction_operations').fetchone()[0] == 'preparing'
