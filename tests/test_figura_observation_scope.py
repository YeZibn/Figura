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


def _png(image: Image.Image) -> bytes:
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_transparent_hidden_rgb_is_neutralized_without_changing_coordinates() -> None:
    outputs = []
    for hidden_color in [(220, 30, 40, 0), (0, 180, 90, 0)]:
        image = Image.new("RGBA", (8, 6), hidden_color)
        image.putpixel((3, 2), (51, 102, 204, 255))
        content = _png(image)
        rgb, mask = decode_scoped_image(content)
        assert rgb.shape == (6, 8, 3)
        assert mask.sum() == 1 and mask[2, 3]
        assert tuple(rgb[2, 3]) == (51, 102, 204)
        assert tuple(rgb[0, 0]) == (255, 255, 255)
        assert _png(image) == content
        outputs.append(rgb)
    np.testing.assert_array_equal(*outputs)


def test_partial_alpha_composites_on_white_and_remains_visible() -> None:
    image = Image.new("RGBA", (3, 2), (0, 0, 0, 128))
    image.putpixel((0, 0), (180, 90, 20, 0))
    rgb, mask = decode_scoped_image(_png(image))
    assert tuple(rgb[1, 1]) == (127, 127, 127)
    assert mask[1, 1] and not mask[0, 0]


def test_scope_intersects_intrinsic_visibility_and_rejects_empty_intersection() -> None:
    image = Image.new("RGBA", (10, 10), (220, 30, 40, 0))
    for y in range(10):
        for x in range(6, 10):
            image.putpixel((x, y), (30, 60, 90, 255))
    rgb, mask = decode_scoped_image(_png(image), {
        "include": [[[500, 0], [1000, 0], [1000, 1000], [500, 1000]]],
        "exclude": [[[800, 0], [1000, 0], [1000, 1000], [800, 1000]]],
    })
    assert mask[3, 6] and not mask[3, 5] and not mask[3, 9]
    assert tuple(rgb[3, 9]) == (255, 255, 255)
    with pytest.raises(ObservationScopeError, match="no visible source pixels"):
        decode_scoped_image(_png(image), {
            "include": [[[0, 0], [400, 0], [400, 1000], [0, 1000]]],
        })


def test_fully_transparent_input_cannot_reach_a_detector() -> None:
    content = _png(Image.new("RGBA", (8, 6), (220, 30, 40, 0)))
    with pytest.raises(ValueError, match="no visible source pixels"):
        decode_scoped_image(content)
    with pytest.raises(ObservationScopeError):
        decode_scoped_image(content, {"exclude": [[[0, 0], [200, 0], [0, 200]]]})


def test_real_panel_crop_hidden_pixels_are_removed_from_observation() -> None:
    from figura.sources.imaging import crop_panel
    from figura.sources.models import PanelPoint

    content = crop_panel(_png(Image.new("RGB", (20, 16), (220, 30, 40))), (
        PanelPoint(0, 0), PanelPoint(1000, 0), PanelPoint(0, 1000),
    ))
    with Image.open(BytesIO(content)) as panel:
        assert panel.getpixel((19, 15)) == (220, 30, 40, 0)
    rgb, mask = decode_scoped_image(content)
    assert rgb.shape == (16, 20, 3)
    assert mask[1, 1] and not mask[15, 19]
    assert tuple(rgb[15, 19]) == (255, 255, 255)


@pytest.mark.parametrize("tool_name", ["extract_text", "measure_bars", "measure_lines", "measure_scatter", "measure_pie"])
def test_observation_feedback_does_not_restore_hidden_source_colors(tool_name) -> None:
    from figura.tools.measurements.visualization import render_measurement_overlay

    outputs = []
    for color in [(220, 30, 40, 0), (0, 180, 90, 0)]:
        image = Image.new("RGBA", (80, 60), color)
        image.putpixel((20, 30), (0, 0, 0, 128))
        image.putpixel((21, 30), (51, 102, 204, 255))
        overlay = render_measurement_overlay(_png(image), {
            "image_size": {"width": 80, "height": 60}, "status": "no_evidence",
        }, tool_name)
        with Image.open(BytesIO(overlay)) as rendered:
            assert rendered.size == (80, 60)
            assert rendered.getpixel((79, 59)) == (255, 255, 255)
            assert rendered.getpixel((20, 30)) == (127, 127, 127)
            assert rendered.getpixel((21, 30)) == (51, 102, 204)
        outputs.append(overlay)
    assert outputs[0] == outputs[1]
