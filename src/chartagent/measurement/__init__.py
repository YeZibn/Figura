"""Bounded measurement domain with stable package-level exports."""

from .evidence import (
    MAX_OBSERVATION_OBJECTIVES,
    MAX_OBSERVATION_REGIONS,
    MAX_REPAIR_ATTEMPTS,
    MEASUREMENT_FOCUS_MODES,
    MEASUREMENT_STATUSES,
    MEASUREMENT_TOOLS,
    OBSERVATION_COORDINATE_SPACES,
    OBSERVATION_REGION_ROLES,
    build_measurement_evidence_refs,
    compact_evidence_ref,
    normalize_evidence_refs,
)
from .lifecycle import (
    MeasurementAttempt,
    MeasurementSession,
    measurement_gate,
    register_measurement,
    sessions_from_state,
    sessions_to_state,
)
from .quality import (
    attach_measurement_quality,
    audit_measurement,
    measurement_from_data,
)
from .scope import (
    MeasurementTarget,
    ObservationScope,
    measurement_target_fingerprint,
    normalize_measurement_target,
    normalize_observation_scope,
    observation_scope_fingerprint,
)
from .evidence import measurement_session_id

__all__ = [
    "MEASUREMENT_TOOLS",
    "MEASUREMENT_STATUSES",
    "MEASUREMENT_FOCUS_MODES",
    "OBSERVATION_COORDINATE_SPACES",
    "OBSERVATION_REGION_ROLES",
    "MAX_OBSERVATION_REGIONS",
    "MAX_OBSERVATION_OBJECTIVES",
    "MAX_REPAIR_ATTEMPTS",
    "MeasurementTarget",
    "ObservationScope",
    "MeasurementAttempt",
    "MeasurementSession",
    "attach_measurement_quality",
    "audit_measurement",
    "build_measurement_evidence_refs",
    "compact_evidence_ref",
    "measurement_from_data",
    "measurement_gate",
    "measurement_target_fingerprint",
    "normalize_observation_scope",
    "observation_scope_fingerprint",
    "measurement_session_id",
    "normalize_evidence_refs",
    "normalize_measurement_target",
    "register_measurement",
    "sessions_from_state",
    "sessions_to_state",
]
