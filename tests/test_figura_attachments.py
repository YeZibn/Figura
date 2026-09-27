from __future__ import annotations

import io
import os
import stat
import uuid
from dataclasses import fields

import pytest
from PIL import Image

from figura.attachments import FiguraAttachmentService
from figura.runtime import FiguraRunStore, RunError, RunErrorCode


def _image_bytes(image_format: str = "PNG") -> bytes:
    content = io.BytesIO()
    Image.new("RGB", (3, 2), color="red").save(content, format=image_format)
    return content.getvalue()


def _attachment_store(tmp_path):
    store = FiguraRunStore(tmp_path)
    session = store.create_session()
    attachments = FiguraAttachmentService(store)
    return store, session, attachments


def test_upload_stores_verified_metadata_and_resolves_original_bytes(tmp_path) -> None:
    store, session, attachments = _attachment_store(tmp_path)
    content = _image_bytes()

    metadata = attachments.upload(session.session_id, "charts/summary.png", content)
    resolved = attachments.resolve(session.session_id, metadata.attachment_id)
    file_path = tmp_path / "attachments" / f"{metadata.attachment_id}.bin"

    assert metadata.filename == "summary.png"
    assert metadata.media_type == "image/png"
    assert metadata.byte_count == len(content)
    assert attachments.list(session.session_id) == (metadata,)
    assert resolved.media_type == "image/png"
    assert resolved.image_bytes == content
    assert file_path.read_bytes() == content
    assert {item.name for item in fields(metadata)} == {
        "attachment_id",
        "session_id",
        "filename",
        "media_type",
        "byte_count",
        "created_at",
    }
    assert str(file_path) not in repr(metadata)
    if os.name == "posix":
        assert stat.S_IMODE(file_path.stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "attachments").stat().st_mode) == 0o700
    assert store.get_attachment_metadata(session.session_id, metadata.attachment_id) == metadata


def test_upload_uses_decoded_media_type_instead_of_filename_extension(tmp_path) -> None:
    _store, session, attachments = _attachment_store(tmp_path)

    metadata = attachments.upload(session.session_id, "not-really.png", _image_bytes("JPEG"))

    assert metadata.filename == "not-really.png"
    assert metadata.media_type == "image/jpeg"


@pytest.mark.parametrize("content", [b"", b"not an image"])
def test_upload_rejects_empty_and_malformed_content_without_metadata(tmp_path, content) -> None:
    _store, session, attachments = _attachment_store(tmp_path)

    with pytest.raises(RunError):
        attachments.upload(session.session_id, "broken.png", content)

    assert attachments.list(session.session_id) == ()
    assert list((tmp_path / "attachments").glob("*.bin")) == []


def test_upload_rejects_unsupported_image_formats(tmp_path) -> None:
    _store, session, attachments = _attachment_store(tmp_path)

    with pytest.raises(RunError) as error:
        attachments.upload(session.session_id, "image.tiff", _image_bytes("TIFF"))

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert attachments.list(session.session_id) == ()


def test_upload_rejects_content_over_provider_image_limit(tmp_path, monkeypatch) -> None:
    import figura.attachments.service as service_module

    _store, session, attachments = _attachment_store(tmp_path)
    monkeypatch.setattr(service_module, "MAX_IMAGE_BYTES", 4)

    with pytest.raises(RunError) as error:
        attachments.upload(session.session_id, "large.png", b"12345")

    assert error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert attachments.list(session.session_id) == ()
    assert list((tmp_path / "attachments").glob("*.bin")) == []


def test_upload_sanitizes_filename_and_rejects_unbounded_names(tmp_path) -> None:
    _store, session, attachments = _attachment_store(tmp_path)

    metadata = attachments.upload(session.session_id, "C:\\private\\chart.png", _image_bytes())
    assert metadata.filename == "chart.png"

    with pytest.raises(RunError):
        attachments.upload(session.session_id, "x" * 256, _image_bytes())


def test_attachment_access_and_delete_are_scoped_to_the_owning_session(tmp_path) -> None:
    store, owner, attachments = _attachment_store(tmp_path)
    other = store.create_session()
    metadata = attachments.upload(owner.session_id, "chart.png", _image_bytes())

    assert attachments.list(other.session_id) == ()
    with pytest.raises(RunError) as read_error:
        attachments.resolve(other.session_id, metadata.attachment_id)
    with pytest.raises(RunError) as delete_error:
        attachments.delete(other.session_id, metadata.attachment_id)
    assert read_error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert delete_error.value.code is RunErrorCode.UNSUPPORTED_PAYLOAD
    assert attachments.resolve(owner.session_id, metadata.attachment_id).image_bytes == _image_bytes()

    attachments.delete(owner.session_id, metadata.attachment_id)
    assert attachments.list(owner.session_id) == ()
    assert not (tmp_path / "attachments" / f"{metadata.attachment_id}.bin").exists()


def test_startup_reconciles_tombstones_and_orphaned_files(tmp_path) -> None:
    store, session, attachments = _attachment_store(tmp_path)
    metadata = attachments.upload(session.session_id, "chart.png", _image_bytes())
    root = tmp_path / "attachments"
    final_path = root / f"{metadata.attachment_id}.bin"
    trash = root / ".trash"
    tombstone = trash / f"{metadata.attachment_id}.{uuid.uuid4().hex}.bin"
    os.replace(final_path, tombstone)
    orphan_id = uuid.uuid4().hex
    orphan_path = root / f"{orphan_id}.bin"
    orphan_path.write_bytes(b"orphan")
    orphan_tombstone = trash / f"{orphan_id}.{uuid.uuid4().hex}.bin"
    orphan_path.replace(orphan_tombstone)

    recovered = FiguraAttachmentService(store)

    assert final_path.read_bytes() == _image_bytes()
    assert not tombstone.exists()
    assert not orphan_tombstone.exists()
    assert recovered.list(session.session_id) == (metadata,)


def test_failed_metadata_registration_removes_installed_file(tmp_path, monkeypatch) -> None:
    store, session, attachments = _attachment_store(tmp_path)

    def fail_after_install(_metadata, install_file):
        install_file()
        raise RunError(RunErrorCode.STORAGE_ERROR)

    monkeypatch.setattr(store, "register_attachment", fail_after_install)

    with pytest.raises(RunError):
        attachments.upload(session.session_id, "chart.png", _image_bytes())

    assert attachments.list(session.session_id) == ()
    assert list((tmp_path / "attachments").glob("*.bin")) == []
