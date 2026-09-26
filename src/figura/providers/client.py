"""Explicit provider factory and normalized synchronous model client."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAIError

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


class ProviderClient:
    """One explicitly selected provider/model pair."""

    def __init__(
        self,
        profile: ProviderProfile,
        policy: ProviderPolicy,
        transport: CompletionTransport,
    ) -> None:
        self.provider_id = profile.provider_id
        self.model_id = profile.model_id
        self._profile = profile
        self._policy = policy
        self._transport = transport

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Make one call. Failures with unknown remote outcomes are never resent."""
        validate_request(request, self.provider_id)
        if request.model_id != self.model_id:
            raise fail(ProviderFailureCode.UNSUPPORTED_MODEL, "请求模型与已创建的模型客户端不匹配。")
        payload = self._policy.build_payload(request)
        try:
            raw_response = self._transport.create(**payload)
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
    ) -> None:
        self._settings = settings or ProviderSettings.from_env()
        self._transport_factory = transport_factory or OpenAISDKTransport

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        transport_factory: Callable[[ProviderProfile], CompletionTransport] | None = None,
    ) -> "ProviderFactory":
        return cls(
            ProviderSettings.from_env(environ),
            transport_factory=transport_factory,
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
        return ProviderClient(profile, policy, transport)


def _provider_failure(error: Exception) -> ProviderFailure:
    if isinstance(error, APITimeoutError):
        return ProviderFailure(
            ProviderFailureCode.TIMEOUT,
            outcome_known=False,
            transient=True,
            safe_message=_safe_message(ProviderFailureCode.TIMEOUT),
        )
    if isinstance(error, APIConnectionError):
        return ProviderFailure(
            ProviderFailureCode.CONNECTION_ERROR,
            outcome_known=False,
            transient=True,
            safe_message=_safe_message(ProviderFailureCode.CONNECTION_ERROR),
        )
    if isinstance(error, APIStatusError):
        status = getattr(error, "status_code", None)
        status_code = status if type(status) is int and 100 <= status <= 599 else None
        remote_outcome_known = (
            status_code is not None and status_code < 500 and status_code != 408
        )
        code = (
            ProviderFailureCode.PROVIDER_REJECTED
            if remote_outcome_known
            else ProviderFailureCode.PROVIDER_UNAVAILABLE
        )
        return ProviderFailure(
            failure_code=code,
            http_status=status_code,
            outcome_known=remote_outcome_known,
            transient=status_code == 408 or status_code == 429 or (status_code is not None and status_code >= 500),
            safe_message=_safe_message(code),
        )
    if isinstance(error, OpenAIError):
        return ProviderFailure(
            ProviderFailureCode.TRANSPORT_ERROR,
            outcome_known=False,
            transient=True,
            safe_message=_safe_message(ProviderFailureCode.TRANSPORT_ERROR),
        )
    return ProviderFailure(
        ProviderFailureCode.TRANSPORT_ERROR,
        outcome_known=False,
        transient=True,
        safe_message=_safe_message(ProviderFailureCode.TRANSPORT_ERROR),
    )


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
