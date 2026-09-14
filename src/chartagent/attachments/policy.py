"""Attachment authorization and size policy constants."""

SUPPORTED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
DEFAULT_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024

__all__ = ["SUPPORTED_IMAGE_TYPES", "DEFAULT_MAX_ATTACHMENT_BYTES"]
