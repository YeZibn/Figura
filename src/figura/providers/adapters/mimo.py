"""Request and response policy for Xiaomi MiMo 2.6 Flash."""

from __future__ import annotations

from typing import Any

from ..errors import ProviderFailureCode
from ..models import MessageRole, ProviderId, ProviderRequest
from ..validation import fail
from .base import ProviderPolicy, resolve_options


class MiMoPolicy(ProviderPolicy):
    provider_id = ProviderId.MIMO

    def validate_configuration(self) -> ProviderFailureCode | None:
        base_error = super().validate_configuration()
        if base_error is not None:
            return base_error
        if self.profile.reasoning_effort is not None:
            return ProviderFailureCode.INVALID_CONFIGURATION
        return None

    def build_payload(self, request: ProviderRequest) -> dict[str, Any]:
        payload = self._base_payload(
            request,
            developer_role_supported=True,
            provider_id=self.provider_id,
        )
        thinking_mode, reasoning_effort = resolve_options(request, self.profile)
        if reasoning_effort is not None:
            raise fail(
                ProviderFailureCode.UNSUPPORTED_CAPABILITY,
                "MiMo v2.6 Flash 不支持 reasoning_effort 设置。",
            )
        _require_tool_continuations(request, thinking_mode)
        payload["extra_body"] = {
            "thinking": {"type": "enabled" if thinking_mode else "disabled"}
        }
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
                "MiMo thinking 模式的工具历史必须包含 reasoning continuation。",
            )
