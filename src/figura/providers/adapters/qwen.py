"""Request and response policy for Qwen 3.8 Flash."""

from __future__ import annotations

from typing import Any

from ..errors import ProviderFailureCode
from ..models import ProviderId, ProviderRequest
from ..validation import fail
from .base import ProviderPolicy, resolve_options


_QWEN_EFFORTS = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}


class QwenPolicy(ProviderPolicy):
    provider_id = ProviderId.QWEN

    def validate_configuration(self) -> ProviderFailureCode | None:
        base_error = super().validate_configuration()
        if base_error is not None:
            return base_error
        effort = self.profile.reasoning_effort
        if effort is not None and effort not in _QWEN_EFFORTS:
            return ProviderFailureCode.INVALID_CONFIGURATION
        if effort == "none" and self.profile.thinking_mode:
            return ProviderFailureCode.INVALID_CONFIGURATION
        if effort not in (None, "none") and not self.profile.thinking_mode:
            return ProviderFailureCode.INVALID_CONFIGURATION
        return None

    def build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload = self._base_payload(
            request,
            developer_role_supported=False,
            provider_id=self.provider_id,
        )
        thinking_mode, reasoning_effort = resolve_options(request, self.profile)
        if reasoning_effort is not None and reasoning_effort not in _QWEN_EFFORTS:
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "Qwen 不支持所选 reasoning_effort。")
        if reasoning_effort == "none" and thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "reasoning_effort=none 与 thinking_mode=true 冲突。")
        if reasoning_effort not in (None, "none") and not thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "启用 reasoning_effort 时必须启用 thinking_mode。")

        payload["extra_body"] = {"preserve_thinking": thinking_mode}
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        elif not thinking_mode:
            payload["reasoning_effort"] = "none"
        return payload
