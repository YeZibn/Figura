"""Provider/configuration readiness checks."""

from __future__ import annotations

from ..client import LLMClient, load_environment, resolve_config
from ..client.config import SUPPORTED_PROVIDERS


def probe_provider_readiness(*, provider: str, model: str | None = None) -> dict[str, str]:
    """Check local Agent configuration without making a provider request."""
    try:
        load_environment()
        # ``model`` is the legacy Gateway/CLI override for the OpenAI relay.
        # Never let it replace the provider-scoped Qwen model.
        config = resolve_config(provider=provider, model=model if provider == "openai" else None)
        if not config.api_key:
            return {"status": "unavailable", "reason": "missing_configuration"}
        LLMClient(config=config)
    except ValueError as exc:
        if "API key" in str(exc):
            return {"status": "unavailable", "reason": "missing_configuration"}
        return {"status": "unavailable", "reason": "invalid_configuration"}
    except Exception:
        return {"status": "unavailable", "reason": "initialization_failed"}
    return {"status": "ready", "provider": config.provider, "model": config.model}


def probe_agent_readiness(*, model: str | None = None) -> dict:
    """Return aggregate safe readiness for the default and supported providers."""
    try:
        load_environment()
        default = resolve_config(model=model).provider
    except ValueError:
        return {
            "status": "unavailable",
            "reason": "invalid_configuration",
            "providers": {},
        }
    except Exception:
        return {
            "status": "unavailable",
            "reason": "initialization_failed",
            "providers": {},
        }
    providers = {
        name: probe_provider_readiness(provider=name, model=model if name == "openai" else None)
        for name in SUPPORTED_PROVIDERS
    }
    selected = providers.get(default, {"status": "unavailable", "reason": "invalid_configuration"})
    return {
        "status": selected.get("status", "unavailable"),
        "reason": selected.get("reason") if selected.get("status") != "ready" else None,
        "provider": default,
        "model": selected.get("model", ""),
        "providers": providers,
    }


__all__ = ["probe_agent_readiness", "probe_provider_readiness"]
