"""Compatibility façade for the Evaluation read-only projection.

Bundle discovery and normalization live in ``reader_projection.py``.  Keep
this module stable for the Gateway adapter, CLI integrations, and existing
workbench imports.
"""

from .reader_projection import (
    EVALUATION_SCHEMA_VERSION,
    MAX_RESOURCE_BYTES,
    EvaluationReader,
    EvaluationReaderError,
    SUPPORTED_IMAGE_TYPES,
)

__all__ = [
    "EVALUATION_SCHEMA_VERSION",
    "EvaluationReader",
    "EvaluationReaderError",
    "SUPPORTED_IMAGE_TYPES",
    "MAX_RESOURCE_BYTES",
]
