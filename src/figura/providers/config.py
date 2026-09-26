"""Provider-scoped Figura configuration resolved from the process environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from .errors import ProviderFailureCode
from .models import MODEL_IDS, ProviderAvailability, ProviderId


_DEFAULT_BASE_URLS = {
    ProviderId.DEEPSEEK: "https://api.deepseek.com",
    ProviderId.MIMO: "https://api.xiaomimimo.com/v1",
}
_DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True)
class ProviderProfile:
    provider_id: ProviderId
    model_id: str
    api_key: str | None = field(repr=False)
    base_url: str | None = field(repr=False)
    timeout_seconds: float
    thinking_mode: bool
    reasoning_effort: str | None
    configuration_error: ProviderFailureCode | None = None

    def availability(self) -> ProviderAvailability:
        reason = self.configuration_error
        if reason is None and not self.api_key:
            reason = ProviderFailureCode.CONFIGURATION_MISSING
        if reason is None and not self.base_url:
            reason = ProviderFailureCode.CONFIGURATION_MISSING
        return ProviderAvailability(
            provider_id=self.provider_id,
            model_id=self.model_id,
            available=reason is None,
            reason_code=reason.value if reason is not None else None,
        )


@dataclass(frozen=True)
class ProviderSettings:
    profiles: Mapping[ProviderId, ProviderProfile]

    def __post_init__(self) -> None:
        if set(self.profiles) != set(ProviderId):
            raise ValueError("provider settings require one profile for each allowlisted provider")
        for provider_id, profile in self.profiles.items():
            if profile.provider_id is not provider_id or profile.model_id != MODEL_IDS[provider_id]:
                raise ValueError("provider profile does not match the fixed provider/model allowlist")
        object.__setattr__(self, "profiles", MappingProxyType(dict(self.profiles)))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProviderSettings":
        values = os.environ if environ is None else environ
        profiles = {
            provider_id: _profile_from_env(provider_id, values)
            for provider_id in ProviderId
        }
        return cls(profiles)

def _profile_from_env(
    provider_id: ProviderId, environ: Mapping[str, str]
) -> ProviderProfile:
    prefix = f"FIGURA_{provider_id.value.upper()}"
    raw_key = environ.get(f"{prefix}_API_KEY", "")
    api_key = raw_key.strip() or None

    raw_base_url = environ.get(f"{prefix}_BASE_URL", "").strip()
    base_url = raw_base_url.rstrip("/") or None
    if base_url is None:
        base_url = _DEFAULT_BASE_URLS.get(provider_id)

    configuration_error: ProviderFailureCode | None = None
    if base_url is not None:
        try:
            parsed_url = urlsplit(base_url)
            valid_url = (
                parsed_url.scheme == "https"
                and bool(parsed_url.netloc)
                and parsed_url.username is None
                and parsed_url.password is None
                and not parsed_url.query
                and not parsed_url.fragment
                and len(base_url) <= 2048
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            configuration_error = ProviderFailureCode.INVALID_CONFIGURATION
    raw_timeout = environ.get(f"{prefix}_TIMEOUT_SECONDS", "60").strip()
    try:
        timeout_seconds = float(raw_timeout)
        if not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ValueError
    except (TypeError, ValueError):
        timeout_seconds = _DEFAULT_TIMEOUT_SECONDS
        configuration_error = ProviderFailureCode.INVALID_CONFIGURATION

    raw_thinking = environ.get(f"{prefix}_THINKING_MODE", "true").strip().lower()
    if raw_thinking in {"1", "true", "yes", "on"}:
        thinking_mode = True
    elif raw_thinking in {"0", "false", "no", "off"}:
        thinking_mode = False
    else:
        thinking_mode = True
        configuration_error = ProviderFailureCode.INVALID_CONFIGURATION

    raw_effort = environ.get(f"{prefix}_REASONING_EFFORT", "").strip().lower()
    reasoning_effort = raw_effort or None
    if provider_id is ProviderId.MIMO and reasoning_effort is not None:
        configuration_error = ProviderFailureCode.INVALID_CONFIGURATION

    return ProviderProfile(
        provider_id=provider_id,
        model_id=MODEL_IDS[provider_id],
        api_key=api_key,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        thinking_mode=thinking_mode,
        reasoning_effort=reasoning_effort,
        configuration_error=configuration_error,
    )
