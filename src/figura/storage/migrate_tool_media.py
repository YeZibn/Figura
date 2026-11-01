"""Explicit, backed-up multimodal result cutover. Never imported by online readers.

Stop the Gateway, then run: python -m figura.storage.migrate_tool_media --data-dir .figura
Rollback requires the paired backup and the previous application version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import ExitStack
from pathlib import Path

from figura.runtime.errors import RunError
from figura.runtime.run_lock import PerRunExecutionLock, RunExecutionOwnership
from figura.shared.media import ResourceImage, ToolImageAttachment, attachment_to_dict
from figura.shared.payloads import ExecutionPayloadLimits, use_payload_read_limits
from figura.shared.resource_refs import ImageResourceRef, ToolResourceRef
from figura.sources.chart_renders import FiguraChartRenderService
from figura.sources.storage import ensure_private_directory
from figura.sources.tool_media import FiguraToolMediaService
from .schema import install_tool_media_constraint, upgrade_pre_media_schema

_SOURCE_DIRS = ('attachments', 'panels', 'chart-renders', 'tool-media', 'session-trash')


def _read_image(path: Path) -> ResourceImage:
    if path.is_symlink() or not path.is_file():
        raise ValueError('media_unavailable')
    return ResourceImage.from_bytes(path.read_bytes())


def migrate(data_root: str | Path, *, fault=None) -> dict[str, object]:
    """Convert only the outer result schema under DB and execution ownership."""
    root = Path(data_root).expanduser().resolve()
    database = root / 'figura.sqlite3'
    if not database.is_file() or database.is_symlink():
        raise ValueError('database_unavailable')
    with PerRunExecutionLock(root).acquire('multimodal-result-maintenance'), ExitStack() as locks:
        connection = sqlite3.connect(database, isolation_level=None)
        locks.callback(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = OFF')
        connection.execute('BEGIN IMMEDIATE')
        version = connection.execute('PRAGMA user_version').fetchone()[0]
        if version == 14:
            connection.rollback()
            return {'status': 'already_current', 'converted': 0}
        if not 0 < version <= 13:
            connection.rollback()
            raise RuntimeError("unsupported_source_schema")
        backup = None
        before = set((root / 'tool-media').rglob('*.png')) if (root / 'tool-media').exists() else set()
        try:
            if connection.execute("SELECT 1 FROM runs WHERE status = 'running' LIMIT 1").fetchone():
                raise RuntimeError('active_run_blocks_migration')
            has_operations = connection.execute("SELECT 1 FROM sqlite_master WHERE name='session_context_compaction_operations'").fetchone()
            if has_operations and connection.execute("SELECT 1 FROM session_context_compaction_operations WHERE status = 'preparing' LIMIT 1").fetchone():
                raise RuntimeError('open_compaction_blocks_migration')
            for row in connection.execute('SELECT run_id FROM runs'):
                locks.enter_context(RunExecutionOwnership(root).acquire(row['run_id']))
                locks.enter_context(PerRunExecutionLock(root).acquire(row['run_id']))
            # BEGIN IMMEDIATE prevents new Runs/uploads/deletions while the paired snapshot is made.
            backup = root / 'maintenance-backups' / uuid.uuid4().hex
            ensure_private_directory(backup, 'paired media migration backup')
            with sqlite3.connect(database) as source, sqlite3.connect(backup / 'figura.sqlite3') as target:
                source.backup(target)
            os.chmod(backup / 'figura.sqlite3', 0o600)
            source_manifest = {}
            for name in _SOURCE_DIRS:
                directory = root / name
                if directory.exists():
                    if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob('*')):
                        raise ValueError('unsafe_sources_tree')
                    shutil.copytree(directory, backup / name)
                    for path in directory.rglob('*'):
                        if path.is_file():
                            source_manifest[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
            audit = {'status': 'prepared', 'source_schema': version, 'target_schema': 14,
                     'target_registry': 'figura-web-v11', 'source_manifest': source_manifest, 'results': []}
            (backup / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
            os.chmod(backup / 'audit.json', 0o600)
            if version < 13:
                upgrade_pre_media_schema(connection, version, validate=False)
            media = FiguraToolMediaService(root)
            renders = FiguraChartRenderService(root)
            rows = connection.execute("""SELECT f.*, r.session_id, r.ordinal FROM run_tool_execution_facts f
                JOIN runs r USING(run_id) ORDER BY r.session_id, r.ordinal, f.tool_sequence""").fetchall()
            calls = {}; descriptors = {}; panels = set()
            connection.execute('DROP TRIGGER immutable_run_tool_fact_update')

            def source_image(row, ref):
                if not isinstance(ref, ImageResourceRef):
                    raise ValueError('not_original_media')
                inputs = connection.execute("""SELECT e.payload_json FROM run_execution_records e
                    JOIN runs r USING(run_id) WHERE r.session_id=? AND r.ordinal<=? AND e.record_kind='input'""",
                    (row['session_id'], row['ordinal'])).fetchall()
                allowed = {item for record in inputs for item in json.loads(record['payload_json'])['attachment_ids']}
                if ref.kind == 'attachment':
                    if ref.id not in allowed or not re.fullmatch('[a-f0-9]{32}', ref.id):
                        raise ValueError('unauthorized_source')
                    metadata = connection.execute('SELECT * FROM attachments WHERE session_id=? AND attachment_id=?',
                                                  (row['session_id'], ref.id)).fetchone()
                    image = _read_image(root / 'attachments' / (ref.id + '.bin'))
                    if metadata is None or metadata['media_type'] != image.media_type or metadata['byte_count'] != len(image.image_bytes):
                        raise ValueError('source_integrity')
                    return image
                if (row['session_id'], ref.id) not in panels or not re.fullmatch('[a-f0-9]{64}', ref.id):
                    raise ValueError('uncommitted_panel')
                metadata = connection.execute('SELECT * FROM panels WHERE session_id=? AND panel_id=?',
                                              (row['session_id'], ref.id)).fetchone()
                if metadata is None or metadata['source_attachment_id'] not in allowed:
                    raise ValueError('unauthorized_panel')
                return _read_image(root / 'panels' / (ref.id + '.png'))

            for row in rows:
                raw = json.loads(row['payload_json'])
                if row['fact_kind'] == 'tool_call':
                    calls[(row['run_id'], row['tool_sequence'])] = raw
                    continue
                if row['fact_kind'] != 'tool_result':
                    continue
                if set(raw) != {'schema_version', 'fact_kind', 'tool_call_sequence', 'attempt_id', 'call_id', 'tool_name', 'outcome', 'result', 'error'}:
                    raise ValueError('invalid_prior_result')
                call = calls[(row['run_id'], raw['tool_call_sequence'])]
                if raw['call_id'] != call['call_id'] or raw['tool_name'] != call['tool_name']:
                    raise ValueError('result_identity_mismatch')
                args = json.loads(call['arguments_json']); result = raw['result']; name = raw['tool_name']
                attached = []; reason = 'nonvisual_or_failed'
                if raw['outcome'] == 'succeeded':
                    try:
                        if name == 'load_image':
                            ref = ImageResourceRef(args['source_kind'], args['source_id'])
                            image = source_image(row, ref)
                            if (result['source_kind'], result['source_id'], result['width'], result['height']) != (ref.kind, ref.id, image.width, image.height):
                                raise ValueError('source_result_mismatch')
                            descriptor = ToolImageAttachment.describe(ref, 'original', image)
                        elif name in {'extract_text', 'measure_chart'}:
                            from figura.tools.implementations.extract_text import EXTRACT_TEXT_RESULT_SCHEMA
                            from figura.tools.measurements.contracts import validate_measurement_result
                            from figura.shared.json_schema import validate_instance
                            from figura.tools.measurements.visualization import render_measurement_overlay
                            if ((name == 'measure_chart' and validate_measurement_result(result) is not None)
                                    or (name == 'extract_text' and validate_instance(result, EXTRACT_TEXT_RESULT_SCHEMA) is not None)):
                                raise ValueError('unsupported_observation_contract')
                            source = ImageResourceRef(args['source_kind'], args['source_id'])
                            if (result['source_kind'], result['source_id']) != (source.kind, source.id):
                                raise ValueError('source_result_mismatch')
                            original = source_image(row, source)
                            image = ResourceImage.from_bytes(render_measurement_overlay(original.image_bytes, result, name))
                            kind = 'ocr' if name == 'extract_text' else 'measurement'
                            ref = ToolResourceRef(kind, row['run_id'], raw['call_id'])
                            descriptor = ToolImageAttachment.describe(ref, kind + '_annotation', image, 'migration_reconstructed')
                            media.install(row['session_id'], descriptor, image)
                        elif name == 'render_chart_figure':
                            png, _, _ = renders.resolve(row['run_id'], raw['call_id'])
                            image = ResourceImage.from_bytes(png)
                            ref = ToolResourceRef('chart_render', row['run_id'], raw['call_id'])
                            descriptor = ToolImageAttachment.describe(ref, 'rendered', image)
                            if any(result.get(k) != v for k, v in (('image_sha256', descriptor.sha256), ('byte_count', descriptor.byte_count),
                                     ('width', descriptor.width), ('height', descriptor.height), ('media_type', descriptor.media_type))):
                                raise ValueError('render_integrity')
                        elif name == 'read_resource_image':
                            raw_ref = args['resource_ref']
                            if raw_ref['kind'] in {'attachment', 'panel'}:
                                ref = ImageResourceRef(**raw_ref); image = source_image(row, ref)
                                descriptor = ToolImageAttachment.describe(ref, 'original', image)
                            else:
                                ref = ToolResourceRef(**raw_ref)
                                descriptor = descriptors[(row['session_id'], ref)]
                        else:
                            descriptor = None
                        if descriptor is not None:
                            attached = [attachment_to_dict(descriptor)]
                            descriptors[(row['session_id'], descriptor.resource_ref)] = descriptor
                            reason = descriptor.provenance
                    except (ValueError, TypeError, KeyError, OSError, RuntimeError, RunError):
                        # Only media is optional during maintenance; canonical business facts remain intact.
                        reason = 'media_unavailable_or_unsupported'
                if name == 'decompose_chart_image' and raw['outcome'] == 'succeeded':
                    panels.update((row['session_id'], item['panel_id']) for item in result['panels'])
                raw.update(schema_version=3, attachments=attached)
                encoded = json.dumps(raw, ensure_ascii=False, separators=(',', ':'))
                from figura.runtime.codecs.tools import decode_tool_fact
                from figura.runtime.models import ToolFactKind
                ceiling = connection.execute('SELECT read_ceiling FROM execution_payload_metadata WHERE singleton=1').fetchone()[0]
                with use_payload_read_limits(ExecutionPayloadLimits(ceiling)):
                    decode_tool_fact(ToolFactKind.TOOL_RESULT, 3, encoded)
                connection.execute("UPDATE run_tool_execution_facts SET schema_version=3, payload_json=? WHERE run_id=? AND tool_sequence=?",
                                   (encoded, row['run_id'], row['tool_sequence']))
                audit['results'].append({'run_id': row['run_id'], 'tool_sequence': row['tool_sequence'], 'media': reason})
                if fault: fault('result_converted')
            connection.execute("""CREATE TRIGGER immutable_run_tool_fact_update BEFORE UPDATE ON run_tool_execution_facts
                BEGIN SELECT RAISE(ABORT, 'immutable tool execution fact'); END""")
            install_tool_media_constraint(connection)
            connection.execute('PRAGMA user_version = 14')
            from .schema import _validate_migration
            _validate_migration(connection)
            audit['status'] = 'ready_to_commit'
            (backup / 'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
            if fault: fault('before_commit')
            connection.commit()
            return {'status': 'completed', 'converted': len(audit['results']), 'backup': str(backup)}
        except Exception:
            connection.rollback()
            for path in (root / 'tool-media').rglob('*.png') if (root / 'tool-media').exists() else ():
                if path not in before:
                    path.unlink()
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description='Backed-up Figura multimodal result cutover (Gateway must be stopped).')
    parser.add_argument('--data-dir', required=True)
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir)
        # Private backup path is printed only by this explicitly invoked maintenance command.
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        parser.exit(1, 'Migration refused or rolled back; keep the paired backup and inspect active work before retrying.\n')


if __name__ == '__main__':
    main()
