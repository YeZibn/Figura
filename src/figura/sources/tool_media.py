"""Private immutable Session media. Publication belongs to the result transaction."""
from __future__ import annotations

import os
import hashlib
import re
import shutil
import tempfile
from pathlib import Path
from PIL import Image
from collections.abc import Mapping
from typing import Callable

from figura.runtime.errors import RunError, RunErrorCode
from figura.shared.media import ResourceImage, ToolImageAttachment
from figura.shared.resource_refs import ImageResourceRef, ToolResourceRef
from figura.tools.contracts import ToolContext, ToolImageOutput, ToolOutput
from .storage import ensure_private_directory, sync_directory


class FiguraToolMediaService:
    def __init__(self, data_root: str | os.PathLike[str]) -> None:
        self._root = Path(data_root).expanduser() / 'tool-media'
        ensure_private_directory(self._root, 'tool media')
        # Never delete candidates in a constructor: another process may own them.

    def _session_path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not re.fullmatch('[a-f0-9]{32}', session_id):
            raise RunError(RunErrorCode.INVALID_REQUEST)
        path = self._root / session_id
        if path.is_symlink():
            raise RunError(RunErrorCode.INTEGRITY_ERROR)
        return path

    def install(self, session_id: str, descriptor: ToolImageAttachment, image: ResourceImage) -> None:
        descriptor.verify(image)
        if descriptor.image_kind not in {'ocr_annotation', 'measurement_annotation'}:
            raise ValueError('only annotation files belong to tool media')
        root = self._session_path(session_id)
        ensure_private_directory(root, 'Session tool media')
        target = root / (descriptor.sha256 + '.png')
        if target.exists() or target.is_symlink():
            self.read(session_id, descriptor)
            return
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            staged = Path(temporary) / 'image.png'
            fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(image.image_bytes)
                output.flush()
                os.fsync(output.fileno())
            try:
                os.link(staged, target)
            except FileExistsError:
                pass
            sync_directory(root)
        self.read(session_id, descriptor)

    def read(self, session_id: str, descriptor: ToolImageAttachment) -> ResourceImage:
        path = self._session_path(session_id) / (descriptor.sha256 + '.png')
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size != descriptor.byte_count:
                raise ValueError('missing or invalid saved media')
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != descriptor.sha256:
                raise ValueError("saved media digest mismatch")
            image = ResourceImage.from_bytes(content)
            descriptor.verify(image)
            return image
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise RunError(RunErrorCode.INTEGRITY_ERROR) from None

    def stage_session_deletion(self, session_trash: Path, session_id: str) -> None:
        source = self._session_path(session_id)
        if source.exists():
            target = session_trash / 'tool-media'
            if target.exists() or target.is_symlink():
                raise OSError('duplicate media staging')
            os.replace(source, target)
            sync_directory(self._root)
            sync_directory(session_trash)

    def restore_session_deletion(self, session_trash: Path) -> None:
        source = session_trash / 'tool-media'
        if not source.exists() and not source.is_symlink():
            return
        target = self._session_path(session_trash.name)
        if source.is_symlink() or not source.is_dir() or target.exists():
            raise OSError('invalid media restore')
        os.replace(source, target)
        sync_directory(self._root)
        sync_directory(session_trash)

    def discard_session_deletion(self, session_trash: Path) -> None:
        source = session_trash / 'tool-media'
        if source.is_symlink():
            raise OSError('invalid media staging')
        if source.exists():
            shutil.rmtree(source)

    def _reconcile_exclusive(self, expected: dict[str, set[str]]) -> None:
        """Caller must hold maintenance ownership excluding ALL writers."""
        for root in self._root.iterdir():
            if root.is_symlink() or not root.is_dir():
                raise RunError(RunErrorCode.INTEGRITY_ERROR)
            self._session_path(root.name)
            for path in root.iterdir():
                if path.is_symlink():
                    raise RunError(RunErrorCode.INTEGRITY_ERROR)
                if path.name not in expected.get(root.name, set()):
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            sync_directory(root)


    def reconcile_idle(self, database) -> bool:
        """Hold the writer barrier and all execution owners before pruning candidates."""
        import json
        from contextlib import ExitStack
        from figura.runtime.run_lock import RunExecutionOwnership, RunExecutionLockUnavailable
        from figura.shared.media import attachment_from_dict
        with database.write() as connection, ExitStack() as locks:
            if connection.execute("SELECT 1 FROM runs WHERE status='running' LIMIT 1").fetchone():
                return False
            if connection.execute("SELECT 1 FROM session_context_compaction_operations WHERE status='preparing' LIMIT 1").fetchone():
                return False
            try:
                for row in connection.execute('SELECT run_id FROM runs'):
                    locks.enter_context(RunExecutionOwnership(database.data_root).acquire(row['run_id']))
            except RunExecutionLockUnavailable:
                return False
            expected = {}
            rows = connection.execute("""SELECT r.session_id, f.payload_json FROM run_tool_execution_facts f
                JOIN runs r USING(run_id) WHERE f.fact_kind='tool_result'""")
            for row in rows:
                for raw in json.loads(row['payload_json'])['attachments']:
                    descriptor = attachment_from_dict(raw)
                    if descriptor.image_kind in {'ocr_annotation', 'measurement_annotation'}:
                        expected.setdefault(row['session_id'], set()).add(descriptor.sha256 + '.png')
            self._reconcile_exclusive(expected)
            return True


class ToolMediaCommitter:
    """Normalize all tool images through one authorization and installation boundary."""
    def __init__(self, media: FiguraToolMediaService,
                 resolve: Callable[[ToolContext, object], tuple[ResourceImage, ToolImageAttachment]], *, renders=None) -> None:
        self._media, self._resolve, self._renders = media, resolve, renders

    def __call__(self, context: ToolContext, output: ToolOutput) -> tuple[ToolImageAttachment, ...]:
        descriptors = tuple(item.descriptor() for item in output.images)
        # Validate all references before installing any new candidates.
        for item, descriptor in zip(output.images, descriptors, strict=True):
            ref = item.resource_ref
            if 'width' in output.result and 'height' in output.result:
                if (output.result['width'], output.result['height']) != (descriptor.width, descriptor.height):
                    raise ValueError('result dimensions differ from media')
            if 'resource_ref' in output.result:
                from dataclasses import asdict
                if dict(output.result['resource_ref']) != asdict(ref):
                    raise ValueError('read reference differs from media')
            producing = isinstance(ref, ToolResourceRef) and (ref.run_id, ref.call_id) == (context.run_id, context.call_id)
            if producing:
                if item.provenance != 'recorded':
                    raise ValueError('new media must be recorded')
                if item.image_kind in {'ocr_annotation', 'measurement_annotation'}:
                    source_ref = ImageResourceRef(output.result.get('source_kind'), output.result.get('source_id'))
                    source, _source_descriptor = self._resolve(context, source_ref)
                    if (source.width, source.height) != (descriptor.width, descriptor.height):
                        raise ValueError('annotation differs from authorized source dimensions')
                    size = output.result.get('image_size')
                    if not isinstance(size, Mapping):
                        raise ValueError('missing source dimensions')
                    if (size.get('width'), size.get('height')) != (item.image.width, item.image.height):
                        raise ValueError('annotation dimensions mismatch')
                elif item.image_kind == 'rendered':
                    if self._renders is None:
                        raise ValueError('render storage required')
                    canonical, _, _ = self._renders.resolve(ref.run_id, ref.call_id)
                    descriptor.verify(ResourceImage.from_bytes(canonical))
                    for key, value in (('image_sha256', descriptor.sha256), ('byte_count', descriptor.byte_count),
                                       ('width', descriptor.width), ('height', descriptor.height), ('media_type', descriptor.media_type)):
                        if output.result.get(key) != value:
                            raise ValueError('render metadata mismatch')
                else:
                    raise ValueError('invalid producing reference')
            else:
                if isinstance(ref, ToolResourceRef) and 'resource_ref' not in output.result:
                    raise ValueError('producing calls must use their own resource identity')
                if isinstance(ref, ImageResourceRef) and 'source_kind' in output.result:
                    if (output.result.get('source_kind'), output.result.get('source_id')) != (ref.kind, ref.id):
                        raise ValueError('source result differs from loaded resource')
                image, committed = self._resolve(context, ref)
                committed.verify(item.image)
                if committed != descriptor or image.image_bytes != item.image.image_bytes:
                    raise ValueError('loaded image differs from authorized resource')
        for item, descriptor in zip(output.images, descriptors, strict=True):
            ref = item.resource_ref
            if (isinstance(ref, ToolResourceRef) and (ref.run_id, ref.call_id) == (context.run_id, context.call_id)
                    and item.image_kind in {'ocr_annotation', 'measurement_annotation'}):
                self._media.install(context.session_id, descriptor, item.image)
        return descriptors
