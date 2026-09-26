"""Safe, bounded errors exposed by the Figura provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProviderFailureCode(str, Enum):
    CONFIGURATION_MISSING = "configuration_missing"
    INVALID_CONFIGURATION = "invalid_configuration"
    UNSUPPORTED_PROVIDER = "unsupported_provider"
    UNSUPPORTED_MODEL = "unsupported_model"
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROVIDER_REJECTED = "provider_rejected"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    CONNECTION_ERROR = "connection_error"
    INCOMPLETE_STREAM = "incomplete_stream"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    TRANSPORT_ERROR = "transport_error"


@dataclass(frozen=True)
class ProviderFailure:
    failure_code: ProviderFailureCode
    outcome_known: bool
    transient: bool
    safe_message: str
    http_status: int | None = None


class ProviderCallError(Exception):
    """An error whose public message and metadata never contain raw SDK data."""

    def __init__(self, failure: ProviderFailure) -> None:
        self.failure = failure
        super().__init__(failure.safe_message)


class ProviderInputError(ProviderCallError):
    pass


class ProviderConfigurationError(ProviderCallError):
    pass


class ProviderProtocolError(Exception):
    def __init__(
        self,
        code: ProviderFailureCode = ProviderFailureCode.INVALID_PROVIDER_RESPONSE,
        *,
        outcome_known: bool = True,
        transient: bool = False,
    ) -> None:
        self.code = code
        self.outcome_known = outcome_known
        self.transient = transient
        super().__init__("provider response could not be normalized")
