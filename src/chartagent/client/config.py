"""Configuration layering for the LLM client.

Precedence per key: explicit parameter > environment variable > default value.
Partially-overridden configs are safe: only the highest-priority source per
key wins; the rest fall through to env/defaults.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

# The OpenAI endpoint is deployment-configured. This default remains for
# backwards compatibility when a local caller has not supplied a relay URL.
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_QWEN_MODEL = "qwen3.8-flash"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-flash"
DEFAULT_PROVIDER = "openai"
SUPPORTED_PROVIDERS = ("openai", "qwen", "deepseek")
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 2

_ENV_PROVIDER = "CHARTAGENT_PROVIDER"
_OPENAI_API_KEY = "OPENAI_API_KEY"
_OPENAI_BASE_URL = "OPENAI_BASE_URL"
_OPENAI_MODEL = "OPENAI_MODEL"
_OPENAI_TIMEOUT = "OPENAI_TIMEOUT"
_OPENAI_MAX_RETRIES = "OPENAI_MAX_RETRIES"
_QWEN_API_KEY = "QWEN_API_KEY"
_QWEN_BASE_URL = "QWEN_BASE_URL"
_QWEN_MODEL = "QWEN_MODEL"
_QWEN_TIMEOUT = "QWEN_TIMEOUT"
_QWEN_MAX_RETRIES = "QWEN_MAX_RETRIES"
_QWEN_ENABLE_THINKING = "QWEN_ENABLE_THINKING"
_DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
_DEEPSEEK_BASE_URL = "DEEPSEEK_BASE_URL"
_DEEPSEEK_MODEL = "DEEPSEEK_MODEL"
_DEEPSEEK_TIMEOUT = "DEEPSEEK_TIMEOUT"
_DEEPSEEK_MAX_RETRIES = "DEEPSEEK_MAX_RETRIES"
_DEEPSEEK_ENABLE_THINKING = "DEEPSEEK_ENABLE_THINKING"
_DEEPSEEK_REASONING_EFFORT = "DEEPSEEK_REASONING_EFFORT"
_LEGACY_ENV_API_KEY = "DASHSCOPE_API_KEY"
_LEGACY_ENV_BASE_URL = "DASHSCOPE_BASE_URL"
_LEGACY_ENV_MODEL = "DASH_MODEL"
_ENV_FILE = "CHARTAGENT_ENV_FILE"


def _default_environment_files() -> tuple[Path, ...]:
    """Return local development candidates without depending on the caller cwd."""
    project_root = Path(__file__).resolve().parents[3]
    return (Path.cwd() / ".env", project_root / ".env")


def load_environment(env_file: str | os.PathLike[str] | None = None) -> None:
    """Load configuration from an explicit or stable local environment file.

    Uses ``python-dotenv``; existing environment variables take precedence over
    values in the file. An explicit path takes precedence over
    ``CHARTAGENT_ENV_FILE``; otherwise the current directory and source-tree
    project root are checked without requiring a duplicate ``frontend/.env``.
    """
    configured = env_file if env_file is not None else os.environ.get(_ENV_FILE)
    candidates = (Path(configured),) if configured else _default_environment_files()
    for candidate in candidates:
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


@dataclass
class ClientConfig:
    """Typed, fully-resolved client configuration.

    Every field has a concrete value selected by the precedence rule, so the
    layer above can trust it without re-deriving sources.
    """

    provider: str = DEFAULT_PROVIDER
    api_key: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    model: str = ""
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    reasoning_effort: Optional[str] = None
    enable_thinking: bool = False


def resolve_config(
    provider: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: Optional[float] = None,
    max_retries: Optional[int] = None,
    reasoning_effort: Optional[str] = None,
    enable_thinking: Optional[bool] = None,
    env: Optional[Mapping[str, str]] = None,
) -> ClientConfig:
    """Merge explicit params > env > defaults into a single ClientConfig.

    `env` is injectable for testing; defaults to ``os.environ``.
    """
    env = env if env is not None else os.environ

    def _env_value(*names: str) -> Optional[str]:
        for name in names:
            value = env.get(name)
            if value is not None and value != "":
                return value
        return None

    def _env_float(*names: str) -> Optional[float]:
        raw = _env_value(*names)
        return float(raw) if raw is not None else None

    def _env_int(*names: str) -> Optional[int]:
        raw = _env_value(*names)
        return int(raw) if raw is not None else None

    def _env_bool(*names: str) -> Optional[bool]:
        raw = _env_value(*names)
        if raw is None:
            return None
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean configuration for {names[0]}")

    selected_provider = provider if provider is not None else (_env_value(_ENV_PROVIDER) or DEFAULT_PROVIDER)
    if not isinstance(selected_provider, str):
        raise ValueError("Unsupported provider; expected openai, qwen, or deepseek")
    selected_provider = selected_provider.strip().lower()
    if selected_provider not in SUPPORTED_PROVIDERS:
        raise ValueError("Unsupported provider; expected openai, qwen, or deepseek")

    if selected_provider == "qwen":
        key_names = (_QWEN_API_KEY, _LEGACY_ENV_API_KEY)
        base_names = (_QWEN_BASE_URL, _LEGACY_ENV_BASE_URL)
        model_names = (_QWEN_MODEL, _LEGACY_ENV_MODEL)
        timeout_names = (_QWEN_TIMEOUT,)
        retry_names = (_QWEN_MAX_RETRIES,)
        default_base_url = DEFAULT_QWEN_BASE_URL
        default_model = DEFAULT_QWEN_MODEL
        default_thinking = True
        thinking_name = _QWEN_ENABLE_THINKING
        reasoning_effort_name = None
    elif selected_provider == "deepseek":
        key_names = (_DEEPSEEK_API_KEY,)
        base_names = (_DEEPSEEK_BASE_URL,)
        model_names = (_DEEPSEEK_MODEL,)
        timeout_names = (_DEEPSEEK_TIMEOUT,)
        retry_names = (_DEEPSEEK_MAX_RETRIES,)
        default_base_url = DEFAULT_DEEPSEEK_BASE_URL
        default_model = DEFAULT_DEEPSEEK_MODEL
        default_thinking = True
        thinking_name = _DEEPSEEK_ENABLE_THINKING
        reasoning_effort_name = _DEEPSEEK_REASONING_EFFORT
    else:
        key_names = (_OPENAI_API_KEY,)
        base_names = (_OPENAI_BASE_URL,)
        model_names = (_OPENAI_MODEL,)
        timeout_names = (_OPENAI_TIMEOUT,)
        retry_names = (_OPENAI_MAX_RETRIES,)
        default_base_url = DEFAULT_BASE_URL
        default_model = ""
        default_thinking = False
        thinking_name = None
        reasoning_effort_name = None

    env_timeout = _env_float(*timeout_names)
    env_max_retries = _env_int(*retry_names)
    env_thinking = _env_bool(thinking_name) if thinking_name is not None else None
    env_reasoning_effort = _env_value(reasoning_effort_name) if reasoning_effort_name else None
    return ClientConfig(
        provider=selected_provider,
        api_key=(
            api_key
            if api_key is not None
            else _env_value(*key_names)
        ),
        base_url=(
            base_url
            if base_url is not None
            else _env_value(*base_names) or default_base_url
        ),
        model=(
            model
            if model is not None
            else _env_value(*model_names) or default_model
        ),
        timeout=(
            timeout
            if timeout is not None
            else (env_timeout if env_timeout is not None else DEFAULT_TIMEOUT)
        ),
        max_retries=(
            max_retries
            if max_retries is not None
            else (env_max_retries if env_max_retries is not None else DEFAULT_MAX_RETRIES)
        ),
        reasoning_effort=(
            reasoning_effort
            if reasoning_effort is not None
            else env_reasoning_effort
        ),
        enable_thinking=(
            enable_thinking
            if enable_thinking is not None
            else (env_thinking if env_thinking is not None else default_thinking)
        ),
    )


def config_from_env(env: Optional[Mapping[str, str]] = None) -> ClientConfig:
    """Build a config from environment variables and defaults only."""
    return resolve_config(env=env)
