"""Configuration layering for the LLM client.

Precedence per key: explicit parameter > environment variable > default value.
Partially-overridden configs are safe: only the highest-priority source per
key wins; the rest fall through to env/defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from dotenv import load_dotenv

# Default target: the Alibaba compatible-mode (OpenAI-compatible) deployment.
DEFAULT_BASE_URL = "https://ws-6x14ipx7f4c4rnqb.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2

_ENV_API_KEY = "DASHSCOPE_API_KEY"
_ENV_BASE_URL = "DASHSCOPE_BASE_URL"
_ENV_MODEL = "DASH_MODEL"
_ENV_TIMEOUT = "OPENAI_TIMEOUT"
_ENV_MAX_RETRIES = "OPENAI_MAX_RETRIES"


def load_environment(env_file: str = ".env") -> None:
    """Load key/base_url/model from a `.env` file into the environment.

    Uses ``python-dotenv``; existing environment variables take precedence over
    values in the file. Call this once before ``resolve_config()`` when you want
    configuration from `.env`.
    """
    load_dotenv(env_file, override=False)


@dataclass
class ClientConfig:
    """Typed, fully-resolved client configuration.

    Every field has a concrete value selected by the precedence rule, so the
    layer above can trust it without re-deriving sources.
    """

    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    model: str = ""
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    enable_thinking: Optional[bool] = None  # provider-specific thinking toggle


def resolve_config(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    enable_thinking: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ClientConfig:
    """Merge explicit params > env > defaults into a single ClientConfig.

    `env` is injectable for testing; defaults to ``os.environ``.
    """
    env = env if env is not None else os.environ

    def _env_float(name: str) -> Optional[float]:
        raw = env.get(name)
        return float(raw) if raw else None

    def _env_int(name: str) -> Optional[int]:
        raw = env.get(name)
        return int(raw) if raw else None

    return ClientConfig(
        api_key=api_key if api_key is not None else env.get(_ENV_API_KEY),
        base_url=base_url if base_url is not None else env.get(_ENV_BASE_URL) or DEFAULT_BASE_URL,
        model=model or env.get(_ENV_MODEL) or "",
        timeout=timeout if timeout is not None else _env_float(_ENV_TIMEOUT) or DEFAULT_TIMEOUT,
        max_retries=(
            max_retries
            if max_retries is not None
            else _env_int(_ENV_MAX_RETRIES) or DEFAULT_MAX_RETRIES
        ),
        enable_thinking=enable_thinking,
    )


def config_from_env(env: Optional[Mapping[str, str]] = None) -> ClientConfig:
    """Build a config from environment variables and defaults only."""
    return resolve_config(env=env)