from __future__ import annotations

from io import BytesIO

import numpy as np
import pytest
from PIL import Image

from figura.tools.measurements.observation_scope import (
    ObservationScopeError,
    build_observation_mask,
    decode_scoped_image,
)


def test_scope_unions_include_polygons_and_excludes_overlapping_pixels() -> None:
    mask = build_observation_mask(
        {
            "include": [
                [[0, 0], [500, 0], [500, 1000], [0, 1000]],
                [[500, 0], [1000, 0], [1000, 1000], [500, 1000]],
            ],
            "exclude": [[[0, 0], [300, 0], [300, 1000], [0, 1000]]],
        },
        width=10,
        height=10,
    )

    assert mask.shape == (10, 10)
    assert not mask[5, 1]
    assert mask[5, 4]
    assert mask[5, 8]


def test_scope_supports_irregular_polygons_and_source_edges() -> None:
    mask = build_observation_mask(
        {"include": [[[0, 0], [1000, 0], [0, 1000]]]},
        width=10,
        height=10,
    )

    assert mask[1, 1]
    assert not mask[8, 8]
    assert mask.dtype == np.bool_


def test_omitted_scope_preserves_the_complete_source_image() -> None:
    output = BytesIO()
    Image.new("RGB", (8, 6), "#3366cc").save(output, format="PNG")

    rgb, mask = decode_scoped_image(output.getvalue())

    assert rgb.shape == (6, 8, 3)
    assert tuple(rgb[2, 3]) == (51, 102, 204)
    assert mask is None


@pytest.mark.parametrize(
    "scope",
    [
        {},
        {"include": []},
        {"include": [[[0, 0], [1000, 0]]]},
        {"include": [[[0, 0], [1000, 0], [0, 1000], [1000, 1000]] * 9]},
        {"include": [[[0, 0], [1001, 0], [0, 1000]]]},
        {"include": [[[False, 0], [1000, 0], [0, 1000]]]},
        {"include": [[[0, 0], [1000, 0], [0, 1000]]], "unexpected": []},
    ],
)
def test_rejects_invalid_scope_shapes_and_values(scope) -> None:
    with pytest.raises(ObservationScopeError):
        build_observation_mask(scope, width=10, height=10)


def test_rejects_scope_that_excludes_every_included_pixel() -> None:
    full_image = [[0, 0], [1000, 0], [1000, 1000], [0, 1000]]
    with pytest.raises(ObservationScopeError, match="no source pixels"):
        build_observation_mask(
            {"include": [full_image], "exclude": [full_image]},
            width=10,
            height=10,
        )
