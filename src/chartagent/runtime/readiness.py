"""Provider/configuration readiness checks."""

from __future__ import annotations

from ..client import LLMClient, load_environment, resolve_config


def probe_agent_readiness(*, model: str | None = None) -> dict[str, str]:
    """Check local Agent configuration without making a provider request."""
    try:
        load_environment()
        config = resolve_config(model=model)
        if not config.api_key:
            return {"status": "unavailable", "reason": "missing_configuration"}
        LLMClient(config=config)
    except ValueError as exc:
        if "API key" in str(exc):
            return {"status": "unavailable", "reason": "missing_configuration"}
        return {"status": "unavailable", "reason": "invalid_configuration"}
    except Exception:
        return {"status": "unavailable", "reason": "initialization_failed"}
    return {"status": "ready"}


__all__ = ["probe_agent_readiness"]
