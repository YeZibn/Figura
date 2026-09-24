"""Local HTTP gateway for the ChartAgent desktop client."""

from .protocol import (
    ContinuationKind,
    GATEWAY_VERSION,
    GatewayFault,
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
    "ContinuationKind",
    "GatewayService",
    "SessionSummary",
    "SessionTranscript",
    "validate_message_text",
    "validate_session_name",
    "validate_provider",
]
