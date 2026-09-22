"""Compatibility façade for the Gateway persistence store.

The implementation lives in :mod:`chartagent.gateway.persistence`.  This
module remains importable because the desktop Gateway and integrations have
historically imported ``GatewayHistoryStore`` from here.
"""

from .persistence import (
    DEFAULT_HISTORY_RETENTION_SECONDS,
    DEFAULT_MAX_HISTORY_ARTIFACTS,
    DEFAULT_MAX_HISTORY_ARTIFACT_BYTES,
    DEFAULT_MAX_HISTORY_EVENTS,
    DEFAULT_MAX_HISTORY_RUNS,
    DEFAULT_RECOVERY_RETENTION_SECONDS,
    GatewayHistoryStore,
    HistoryStoreError,
)

__all__ = [
    "GatewayHistoryStore",
    "HistoryStoreError",
    "DEFAULT_MAX_HISTORY_EVENTS",
    "DEFAULT_MAX_HISTORY_RUNS",
    "DEFAULT_HISTORY_RETENTION_SECONDS",
    "DEFAULT_MAX_HISTORY_ARTIFACT_BYTES",
    "DEFAULT_MAX_HISTORY_ARTIFACTS",
    "DEFAULT_RECOVERY_RETENTION_SECONDS",
]
