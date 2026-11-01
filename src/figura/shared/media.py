"""Validated, provider-neutral media values. Only ResourceImage holds pixels."""
from __future__ import annotations

import hashlib
import io
import re
import warnings
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Literal, TypeAlias

from PIL import Image

from .image_limits import MAX_IMAGE_BYTES
from .resource_refs import ImageResourceRef, ResourceRef, ToolResourceRef

ImageKind: TypeAlias = Literal['original', 'ocr_annotation', 'measurement_annotation', 'rendered']
MediaProvenance: TypeAlias = Literal['recorded', 'migration_reconstructed']
_FORMATS = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'GIF': 'image/gif', 'WEBP': 'image/webp'}
_KINDS = {'original': {'attachment', 'panel'}, 'ocr_annotation': {'ocr'},
          'measurement_annotation': {'measurement'}, 'rendered': {'chart_render'}}


@dataclass(frozen=True)
class ResourceImage:
    media_type: str
    image_bytes: bytes = field(repr=False)
    width: int
    height: int

    def __post_init__(self) -> None:
        if not isinstance(self.image_bytes, bytes) or not 0 < len(self.image_bytes) <= MAX_IMAGE_BYTES:
            raise ValueError('invalid image bytes')
        if any(type(n) is not int or n < 1 for n in (self.width, self.height)):
            raise ValueError('invalid image dimensions')
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(self.image_bytes)) as image:
                if image.size != (self.width, self.height) or _FORMATS.get(image.format) != self.media_type:
                    raise ValueError('image metadata mismatch')
                image.verify()
            with Image.open(io.BytesIO(self.image_bytes)) as image:
                image.load()

    @classmethod
    def from_bytes(cls, content: bytes) -> ResourceImage:
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_IMAGE_BYTES:
            raise ValueError("invalid image bytes")
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                return cls(_FORMATS.get(image.format, ''), content, image.width, image.height)


@dataclass(frozen=True)
class ToolImageAttachment:
    resource_ref: ResourceRef
    image_kind: ImageKind
    media_type: str
    width: int
    height: int
    byte_count: int
    sha256: str
    provenance: MediaProvenance = 'recorded'

    def __post_init__(self) -> None:
        if not isinstance(self.resource_ref, (ImageResourceRef, ToolResourceRef)):
            raise ValueError('invalid media reference')
        if self.resource_ref.kind not in _KINDS.get(self.image_kind, set()):
            raise ValueError('image kind does not match resource')
        if self.media_type not in _FORMATS.values() or (self.image_kind != 'original' and self.media_type != 'image/png'):
            raise ValueError('invalid media type')
        if any(type(n) is not int or n < 1 for n in (self.width, self.height, self.byte_count)) or self.byte_count > MAX_IMAGE_BYTES:
            raise ValueError('invalid media size')
        if not isinstance(self.sha256, str) or not re.fullmatch('[0-9a-f]{64}', self.sha256):
            raise ValueError('invalid media digest')
        if self.provenance not in {'recorded', 'migration_reconstructed'}:
            raise ValueError('invalid media provenance')
        if self.provenance == 'migration_reconstructed' and self.image_kind not in {'ocr_annotation', 'measurement_annotation'}:
            raise ValueError('only annotations may be reconstructed')

    @classmethod
    def describe(cls, ref: ResourceRef, kind: ImageKind, image: ResourceImage,
                 provenance: MediaProvenance = 'recorded') -> ToolImageAttachment:
        return cls(ref, kind, image.media_type, image.width, image.height,
                   len(image.image_bytes), hashlib.sha256(image.image_bytes).hexdigest(), provenance)

    def verify(self, image: ResourceImage) -> None:
        if self != self.describe(self.resource_ref, self.image_kind, image, self.provenance):
            raise ValueError('saved image does not match committed descriptor')


def attachment_to_dict(value: ToolImageAttachment) -> dict[str, object]:
    return asdict(value)


def attachment_from_dict(value: object) -> ToolImageAttachment:
    keys = {'resource_ref', 'image_kind', 'media_type', 'width', 'height', 'byte_count', 'sha256', 'provenance'}
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError('invalid attachment fields')
    raw = value['resource_ref']
    if not isinstance(raw, Mapping):
        raise ValueError('invalid reference')
    if set(raw) == {'kind', 'id'}:
        ref = ImageResourceRef(**raw)
    elif set(raw) == {'kind', 'run_id', 'call_id'}:
        ref = ToolResourceRef(**raw)
    else:
        raise ValueError('invalid reference fields')
    return ToolImageAttachment(**{**value, 'resource_ref': ref})
