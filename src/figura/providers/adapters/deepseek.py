"""Request and response policy for DeepSeek Flash."""

from __future__ import annotations

from typing import Any

from ..errors import ProviderFailureCode
from ..models import MessageRole, ProviderId, ProviderRequest
from ..validation import fail
from .base import ProviderPolicy, resolve_options


_DEEPSEEK_EFFORTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
    "ultra",
}


class DeepSeekPolicy(ProviderPolicy):
    provider_id = ProviderId.DEEPSEEK

    def validate_configuration(self) -> ProviderFailureCode | None:
        base_error = super().validate_configuration()
        if base_error is not None:
            return base_error
        effort = self.profile.reasoning_effort
        if effort is not None and effort not in _DEEPSEEK_EFFORTS:
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
        if reasoning_effort is not None and reasoning_effort not in _DEEPSEEK_EFFORTS:
            raise fail(ProviderFailureCode.UNSUPPORTED_CAPABILITY, "DeepSeek 不支持所选 reasoning_effort。")
        if reasoning_effort == "none" and thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "reasoning_effort=none 与 thinking_mode=true 冲突。")
        if reasoning_effort not in (None, "none") and not thinking_mode:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "启用 reasoning_effort 时必须启用 thinking_mode。")

        _require_tool_continuations(request, thinking_mode)
        payload["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_mode else "disabled"}
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort
        return payload


def _require_tool_continuations(request: ProviderRequest, thinking_mode: bool) -> None:
    if not thinking_mode or not request.tools:
        return
    for message in request.messages:
        if (
            message.role is MessageRole.ASSISTANT
            and message.continuation is None
        ):
            raise fail(
                ProviderFailureCode.INVALID_REQUEST,
                "DeepSeek thinking 模式的工具历史必须包含 reasoning continuation。",
            )
