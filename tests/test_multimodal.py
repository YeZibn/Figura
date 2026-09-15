"""Tests for the multimodal content builder (no network, stdlib + Pillow).

Pillow is used only to produce real PNG/JPEG bytes on disk; the builder itself
never imports it.
"""

from __future__ import annotations

import base64

import pytest
from PIL import Image

from chartagent import build_user_content

# Smallest valid 1x1 PNG, for a dependency-free fixture.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _png(tmp_path, name="a.png") -> str:
    p = tmp_path / name
    p.write_bytes(TINY_PNG)
    return str(p)


def _jpeg(tmp_path, name="b.jpg") -> str:
    p = tmp_path / name
    Image.new("RGB", (4, 4), (10, 20, 30)).save(p, format="JPEG")
    return str(p)


def test_png_round_trip(tmp_path):
    path = _png(tmp_path)
    content = build_user_content("look", [path])
    assert content[0] == {"type": "text", "text": "look"}
    part = content[1]
    assert part["type"] == "image_url"
    url = part["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    payload = url.split("base64,", 1)[1]
    assert base64.b64decode(payload) == TINY_PNG


def test_jpeg_mime(tmp_path):
    content = build_user_content("x", [_jpeg(tmp_path)])
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.png"):
        build_user_content("x", [str(tmp_path / "nope.png")])


def test_non_image_extension_raises(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("hi", encoding="utf-8")
    with pytest.raises(ValueError, match="not a recognized image"):
        build_user_content("x", [str(p)])


def test_multiple_paths_keep_order(tmp_path):
    a = _png(tmp_path, "a.png")
    b = _jpeg(tmp_path, "b.jpg")
    content = build_user_content("two", [a, b])
    assert len(content) == 3
    assert content[1]["image_url"]["url"].startswith("data:image/png;")
    assert content[2]["image_url"]["url"].startswith("data:image/jpeg;")
