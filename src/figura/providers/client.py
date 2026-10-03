"""Explicit provider factory and normalized synchronous model client."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
import hashlib
import json
import math
import httpx
from types import MappingProxyType
from figura.shared.payloads import ExecutionPayloadLimits, payload_scope, encode_json
from .retries import classify_failure
from .validation import request_projection
from typing import Any


from .adapters import DeepSeekPolicy, MiMoPolicy, QwenPolicy
from .adapters.base import ProviderPolicy
from .config import ProviderProfile, ProviderSettings
from .errors import (
    ProviderCallError,
    ProviderConfigurationError,
    ProviderFailure,
    ProviderFailureCode,
    ProviderProtocolError,
)
from .models import (
    MODEL_IDS,
    ProviderAvailability,
    ProviderId,
    ImageBlock,
    ProviderRequest,
    ProviderResponse,
)
from .transport import CompletionTransport, OpenAISDKTransport
from .validation import coerce_provider_id, fail, validate_request


_POLICIES: dict[ProviderId, type[ProviderPolicy]] = {
    ProviderId.QWEN: QwenPolicy,
    ProviderId.DEEPSEEK: DeepSeekPolicy,
    ProviderId.MIMO: MiMoPolicy,
}


@dataclass(frozen=True, repr=False)
class _PreparedProviderCall:
    owner: object = field(repr=False)
    request: ProviderRequest = field(repr=False)
    payload: Mapping[str, Any] = field(repr=False)
    descriptor: Mapping[str, Any] = field(repr=False)

    def __reduce__(self) -> object:
        raise TypeError("Prepared provider calls cannot be serialized")


class ProviderClient:
    """One explicitly selected provider/model pair."""

    def __init__(
        self,
        profile: ProviderProfile,
        policy: ProviderPolicy,
        transport: CompletionTransport,
        payload_limits: ExecutionPayloadLimits | None = None,
    ) -> None:
        self.payload_limits = payload_limits or ExecutionPayloadLimits.from_env()
        self.provider_id = profile.provider_id
        self.model_id = profile.model_id
        self._profile = profile
        self._policy = policy
        self._transport = transport
        self._preparation_token = object()

    @payload_scope
    def prepare(self, request: ProviderRequest, *, frozen_options: bool = False, frozen_timeout_seconds: float | None = None) -> _PreparedProviderCall:
        """Validate and build one provider payload without contacting the service."""
        validate_request(request, self.provider_id)
        if request.model_id != self.model_id:
            raise fail(
                ProviderFailureCode.UNSUPPORTED_MODEL,
                "请求模型与已创建的模型客户端不匹配。",
            )
        thinking = request.options.thinking_mode if frozen_options or request.options.thinking_mode is not None else self._profile.thinking_mode
        effort = request.options.reasoning_effort if frozen_options or request.options.reasoning_effort is not None else self._profile.reasoning_effort
        completion = request.options.max_completion_tokens if frozen_options or request.options.max_completion_tokens is not None else self._profile.max_completion_tokens
        request = replace(request, options=replace(request.options, thinking_mode=thinking,
            reasoning_effort=effort, max_completion_tokens=completion, schema_version=2))
        effective_policy = type(self._policy)(replace(self._profile, thinking_mode=thinking,
            reasoning_effort=effort, max_completion_tokens=completion))
        payload = effective_policy.build_payload(request)
        timeout = self._profile.timeout_seconds if frozen_timeout_seconds is None else frozen_timeout_seconds
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise fail(ProviderFailureCode.INVALID_REQUEST, "模型请求超时配置无效。")
        payload["timeout"] = timeout
        endpoint = str(httpx.URL((self._profile.base_url or "").rstrip("/") + "/chat/completions"))
        endpoint_binding = hashlib.sha256(endpoint.encode()).hexdigest()
        fingerprint_input = {"method": "POST", "path": "/chat/completions", "endpoint_binding": endpoint_binding, "payload": payload}
        digest = hashlib.sha256()
        for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).iterencode(fingerprint_input):
            digest.update(chunk.encode("utf-8"))
        projection = request_projection(request)
        images = []
        for message in request.messages:
            if isinstance(message.content, str):
                continue
            for block in message.content:
                if isinstance(block, ImageBlock):
                    images.append({"source_ref": block.source_ref,
                        "observation_kind": block.observation_kind,
                        "media_type": block.media_type, "byte_count": len(block.image_bytes),
                        "sha256": hashlib.sha256(block.image_bytes).hexdigest()})
        contract = request.asset_contract or {
            "prompt_digest": hashlib.sha256(encode_json(projection["instructions"]).encode()).hexdigest(),
            "registry_version": "provider-direct-v1",
            "registry_digest": hashlib.sha256(encode_json(projection["tools"]).encode()).hexdigest(),
        }
        manifest = {**contract, "adapter_contract_version": 1, "images": images}
        descriptor = {"provider_id": self.provider_id.value, "model_id": self.model_id,
            "endpoint_binding": endpoint_binding,
            "request_fingerprint": digest.hexdigest(),
            "options": {"max_completion_tokens": completion, "stream": request.options.stream,
                "thinking_mode": thinking, "reasoning_effort": effort, "timeout_seconds": timeout},
            "asset_manifest": manifest}
        encode_json(descriptor)
        return _PreparedProviderCall(self._preparation_token, request, _freeze(payload), _freeze(descriptor))

    @payload_scope
    def dispatch(self, prepared: _PreparedProviderCall) -> ProviderResponse:
        """Send the exact locally prepared payload once."""
        if (
            not isinstance(prepared, _PreparedProviderCall)
            or prepared.owner is not self._preparation_token
        ):
            raise fail(
                ProviderFailureCode.INVALID_REQUEST,
                "预处理模型请求与当前客户端不匹配。",
            )
        request = prepared.request
        try:
            raw_response = self._transport.create(**_thaw(prepared.payload))
            if request.options.stream:
                return self._policy.normalize_stream(raw_response, request)
            return self._policy.normalize(raw_response, request)
        except ProviderCallError:
            raise
        except ProviderProtocolError as error:
            failure = ProviderFailure(
                failure_code=error.code,
                outcome_known=error.outcome_known,
                transient=error.transient,
                safe_message=_safe_message(error.code),
            )
            raise ProviderCallError(failure) from None
        except Exception as error:
            failure = _provider_failure(error)
            raise ProviderCallError(failure) from None

    def close(self) -> None:
        close = getattr(self._transport, "close", None)
        if callable(close):
            close()


class ProviderFactory:
    """Build clients only for explicit, allowlisted provider/model selections."""

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        *,
        transport_factory: Callable[[ProviderProfile], CompletionTransport] | None = None,
        payload_limits: ExecutionPayloadLimits | None = None,
    ) -> None:
        self.payload_limits = payload_limits or ExecutionPayloadLimits.from_env()
        self._settings = settings or ProviderSettings.from_env()
        self._transport_factory = transport_factory or OpenAISDKTransport

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        transport_factory: Callable[[ProviderProfile], CompletionTransport] | None = None,
        payload_limits: ExecutionPayloadLimits | None = None,
    ) -> "ProviderFactory":
        return cls(
            ProviderSettings.from_env(environ),
            transport_factory=transport_factory, payload_limits=payload_limits,
        )

    def availability(self) -> tuple[ProviderAvailability, ...]:
        results: list[ProviderAvailability] = []
        for provider_id in ProviderId:
            profile = self._settings.profiles[provider_id]
            availability = profile.availability()
            if availability.available:
                policy = _POLICIES[provider_id](profile)
                configuration_error = policy.validate_configuration()
                if configuration_error is not None:
                    availability = ProviderAvailability(
                        provider_id=provider_id,
                        model_id=profile.model_id,
                        available=False,
                        reason_code=configuration_error.value,
                    )
            results.append(availability)
        return tuple(results)

    def create(self, provider_id: ProviderId | str, model_id: str) -> ProviderClient:
        selected_provider = coerce_provider_id(provider_id)
        expected_model = MODEL_IDS[selected_provider]
        if model_id != expected_model:
            raise fail(ProviderFailureCode.UNSUPPORTED_MODEL, "该模型不在此服务商的允许列表中。")

        profile = self._settings.profiles[selected_provider]
        availability = profile.availability()
        policy = _POLICIES[selected_provider](profile)
        configuration_error = policy.validate_configuration()
        reason = availability.reason_code or (
            configuration_error.value if configuration_error is not None else None
        )
        if reason is not None:
            failure_code = ProviderFailureCode(reason)
            raise ProviderConfigurationError(
                ProviderFailure(
                    failure_code=failure_code,
                    outcome_known=True,
                    transient=False,
                    safe_message=_configuration_message(failure_code),
                )
            ) from None
        try:
            transport = self._transport_factory(profile)
        except Exception:
            raise ProviderConfigurationError(
                ProviderFailure(
                    failure_code=ProviderFailureCode.INVALID_CONFIGURATION,
                    outcome_known=True,
                    transient=False,
                    safe_message="模型服务商客户端配置无效。",
                )
            ) from None
        return ProviderClient(profile, policy, transport, self.payload_limits)


def _provider_failure(error: Exception) -> ProviderFailure:
    return classify_failure(error)


def _configuration_message(code: ProviderFailureCode) -> str:
    if code is ProviderFailureCode.CONFIGURATION_MISSING:
        return "所选模型服务商缺少必需的本地配置。"
    return "所选模型服务商配置无效。"


def _safe_message(code: ProviderFailureCode) -> str:
    messages = {
        ProviderFailureCode.PROVIDER_REJECTED: "模型服务商拒绝了本次请求。",
        ProviderFailureCode.PROVIDER_UNAVAILABLE: "模型服务商暂时无法完成本次请求。",
        ProviderFailureCode.TIMEOUT: "等待模型服务商响应超时，远端结果未知。",
        ProviderFailureCode.CONNECTION_ERROR: "与模型服务商的连接中断，远端结果未知。",
        ProviderFailureCode.INCOMPLETE_STREAM: "模型流式响应未完整结束，远端结果未知。",
        ProviderFailureCode.INVALID_PROVIDER_RESPONSE: "模型服务商返回了无法识别的响应。",
        ProviderFailureCode.TRANSPORT_ERROR: "模型请求传输失败，远端结果未知。",
    }
    return messages.get(code, "模型服务调用失败。")


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value
