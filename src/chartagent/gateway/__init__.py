"""Local HTTP gateway for the ChartAgent desktop client."""

from .protocol import (
    CheckpointPhase,
    ContinuationKind,
    GATEWAY_VERSION,
    GatewayFault,
    OperationState,
    RecoveryStatus,
    SessionSummary,
    SessionTranscript,
    validate_message_text,
    validate_session_name,
    validate_provider,
)
from .service import GatewayService

__all__ = [
    "GATEWAY_VERSION",
    "GatewayFault",
    "RecoveryStatus",
    "CheckpointPhase",
    "OperationState",
    "ContinuationKind",
    "GatewayService",
    "SessionSummary",
    "SessionTranscript",
    "validate_message_text",
    "validate_session_name",
    "validate_provider",
]
