"""Approximate model input counts; no request content leaves this module."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile

import tiktoken

ESTIMATOR_VERSION = "tiktoken-o200k-v1"
IMAGE_TOKENS = 1024
_ENCODING_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
_ENCODING_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContextEstimate:
    input_tokens: int
    context_window_tokens: int | None
    estimator_version: str = ESTIMATOR_VERSION


@lru_cache(maxsize=1)
def cached_encoding() -> tiktoken.Encoding | None:
    """Prewarm once from a verified deployment cache; missing cache disables counts."""
    try:
        cache_dir = os.environ.get("TIKTOKEN_CACHE_DIR", os.environ.get(
            "DATA_GYM_CACHE_DIR", os.path.join(tempfile.gettempdir(), "data-gym-cache")
        ))
        if not cache_dir:
            raise ValueError("cache disabled")
        path = Path(cache_dir) / hashlib.sha1(_ENCODING_URL.encode()).hexdigest()
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != _ENCODING_SHA256:
            raise ValueError("cache invalid")
        # Construct from the verified bytes, not the library's network-capable loader.
        # The pattern and special token IDs are o200k_base's published definition.
        import base64
        ranks = {base64.b64decode(token): int(rank) for token, rank in
                 (line.split() for line in data.splitlines() if line)}
        pattern = "|".join([
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?",
            r"\p{N}{1,3}", r" ?[^\s\p{L}\p{N}]+[\r\n/]*",
            r"\s*[\r\n]+", r"\s+(?!\S)", r"\s+",
        ])
        return tiktoken.Encoding(name="o200k_base", pat_str=pattern,
            mergeable_ranks=ranks, special_tokens={"<|endoftext|>": 199999, "<|endofprompt|>": 200018})
    except Exception:
        _LOGGER.warning("本地上下文估算不可用，请预先准备 o200k_base 编码缓存。")
        return None


def input_projection(payload: Mapping[str, object]) -> tuple[dict, int]:
    """Copy only model input; replace genuine image blocks without reading bytes."""
    images = 0

    def copy(value):
        if isinstance(value, Mapping):
            return {key: copy(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [copy(item) for item in value]
        return value

    messages = []
    for message in payload["messages"]:
        item = {key: copy(value) for key, value in message.items() if key != "content"}
        content = message.get("content")
        if isinstance(content, (tuple, list)):
            blocks = []
            for block in content:
                if isinstance(block, Mapping) and block.get("type") == "image_url":
                    images += 1
                    image = {key: copy(value) for key, value in block.items() if key != "image_url"}
                    options = block.get("image_url", {})
                    image["image_url"] = {key: copy(value) for key, value in options.items() if key != "url"}
                    image["image_url"]["url"] = "[image]"
                    blocks.append(image)
                else:
                    blocks.append(copy(block))
            item["content"] = blocks
        elif "content" in message:
            item["content"] = content
        messages.append(item)
    result = {"messages": messages}
    if "tools" in payload:
        result["tools"] = copy(payload["tools"])
    return result, images


def estimate_text_tokens(text: str, encoding: tiktoken.Encoding | None = None) -> int | None:
    """Estimate a history text fragment with the shared local tokenizer."""
    if not isinstance(text, str):
        return None
    selected = cached_encoding() if encoding is None else encoding
    if selected is None:
        return None
    try:
        return len(selected.encode_ordinary(text))
    except Exception:
        _LOGGER.warning("本次历史片段的本地 Token 估算不可用。")
        return None


def estimate_input(payload: Mapping[str, object], capacity: int | None,
                   encoding: tiktoken.Encoding | None) -> ContextEstimate | None:
    if encoding is None:
        return None
    try:
        projection, images = input_projection(payload)
        text = json.dumps(projection, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":"))
        capacity = capacity if type(capacity) is int and capacity > 0 else None
        return ContextEstimate(len(encoding.encode_ordinary(text)) + images * IMAGE_TOKENS, capacity)
    except Exception:
        _LOGGER.warning("本次请求的本地上下文估算不可用。")
        return None
